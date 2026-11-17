//
// Created by gnx91527 on 19/07/18.
//

#include <TristanDefinitions.h>
#include "TristanProcessCoordinator.h"
#include "DebugLevelLogger.h"

namespace FrameProcessor {
    TristanProcessCoordinator::TristanProcessCoordinator() :
    rank_(0),
    daq_version_(-1),
    current_ts_wrap_(0),
    current_ts_buffer_(0),
    dropped_packets_(0),
    invalid_packets_(0),
    timestamp_mismatches_(0),
    processed_jobs_(0),
    processed_frames_(0),
    output_frames_(0),
    last_written_ts_index_(0),
    metaPtr_(0),
    frame_qty_(TRISTAN::frame_qty),
    acq_id_("")
    {
        // Setup logging for the class
        logger_ = Logger::getLogger("FP.TristanProcessCoordinator");
        LOG4CXX_TRACE(logger_, "TristanProcessCoordinator constructor.");

        // Create the work queue for processing jobs
        jobQueue_ = boost::shared_ptr<WorkQueue<boost::shared_ptr<TristanProcessJob> > >(new WorkQueue<boost::shared_ptr<TristanProcessJob> >);
        // Create the work queue for completed jobs
        resultsQueue_ = boost::shared_ptr<WorkQueue<boost::shared_ptr<TristanProcessJob> > >(new WorkQueue<boost::shared_ptr<TristanProcessJob> >);

        // Create a stack of process job objects ready to work
        for (int index = 0; index < TRISTAN::num_primary_packets*2; index++){
            jobStack_.push(boost::shared_ptr<TristanProcessJob>(new TristanProcessJob(TRISTAN::primary_packet_size/sizeof(uint64_t))));
        }

        // Create the buffer managers
        init_buffer_managers();

        // Initialise the ts index vector
        ts_index_array_.assign(TRISTAN::time_slice_write_size * TRISTAN::number_of_time_slice_buffers, 0);

        // Configure threads for processing
        // Now start the worker thread to monitor the queue
        for (size_t index = 0; index < TRISTAN::number_of_processing_threads; index++){
            thread_[index] = new boost::thread(&TristanProcessCoordinator::processTask, this);
        }
    }

    void TristanProcessCoordinator::init_buffer_managers()
    {
        // Create the buffer managers
        // This should be called whenever the qty is reset by config.
        // Any stored points would be lost
        LOG4CXX_DEBUG(logger_, "Initialising the buffers to " << frame_qty_);
        timeStampBuffer_ = boost::shared_ptr<TristanBuffer>(new TristanBuffer(frame_qty_, "event_time_offset", UINT64_TYPE));
        idBuffer_ = boost::shared_ptr<TristanBuffer>(new TristanBuffer(frame_qty_, "event_id", UINT32_TYPE));
        energyBuffer_ = boost::shared_ptr<TristanBuffer>(new TristanBuffer(frame_qty_, "event_energy", UINT32_TYPE));
        ctrlWordBuffer_ = boost::shared_ptr<TristanBuffer>(new TristanBuffer(frame_qty_, "cue_id", UINT16_TYPE));
        ctrlTimeStampBuffer_ = boost::shared_ptr<TristanBuffer>(new TristanBuffer(frame_qty_, "cue_timestamp_zero", UINT64_TYPE));
    }

    void TristanProcessCoordinator::set_frame_qty(size_t qty)
    {
        frame_qty_ = qty;
    }

    size_t TristanProcessCoordinator::get_frame_qty()
    {
        return frame_qty_;
    }

    void TristanProcessCoordinator::get_statistics(uint32_t *dropped_packets,
                                                 uint32_t *invalid_packets,
                                                 uint32_t *timestamp_mismatches,
                                                 uint32_t *processed_jobs,
                                                 uint32_t *job_q_size,
                                                 uint32_t *result_q_size,
                                                 uint32_t *processed_frames,
                                                 uint32_t *output_frames)
    {
        *dropped_packets = dropped_packets_;
        *invalid_packets = invalid_packets_;
        *timestamp_mismatches = timestamp_mismatches_;
        *processed_jobs = processed_jobs_;
        *job_q_size = jobQueue_->size();
        *result_q_size = resultsQueue_->size();
        *processed_frames = processed_frames_;
        *output_frames = output_frames_;
    }

    void TristanProcessCoordinator::register_meta_message_publisher(MetaMessagePublisher *ptr)
    {
        metaPtr_ = ptr;
    }

    void TristanProcessCoordinator::set_acquisition_id(const std::string& acq_id)
    {
        acq_id_ = acq_id;
    }

    void TristanProcessCoordinator::reset_statistics()
    {
        dropped_packets_ = 0;
        invalid_packets_ = 0;
        timestamp_mismatches_ = 0;
        processed_jobs_ = 0;
        processed_frames_ = 0;
        output_frames_ = 0;
    }

    TristanProcessCoordinator::~TristanProcessCoordinator()
    {

    }

    void TristanProcessCoordinator::configure_process(size_t processes, size_t rank)
    {
        // Record the rank
        rank_ = rank;
        // Configure each of the buffer objects
        timeStampBuffer_->configureProcess(processes, rank);
        idBuffer_->configureProcess(processes, rank);
        energyBuffer_->configureProcess(processes, rank);
        ctrlWordBuffer_->configureProcess(processes, rank);
        ctrlTimeStampBuffer_->configureProcess(processes, rank);
    }

    std::vector<boost::shared_ptr<Frame> > TristanProcessCoordinator::process_frame(boost::shared_ptr<Frame> frame)
    {
        LOG4CXX_DEBUG_LEVEL(2, logger_, "Adding frame " << frame->get_frame_number() << " to coordinator");
        std::vector<boost::shared_ptr<Frame> > frames;
        const TRISTAN::FrameHeader* hdrPtr = static_cast<const TRISTAN::FrameHeader*>(frame->get_data_ptr());
        if (hdrPtr->idle_frame == 0) {
            // This is a standard frame so process the packets as normal
            this->frame_to_jobs(frame);
            //LOG4CXX_ERROR(logger_, "Current wrap: " << current_ts_wrap_);
            //LOG4CXX_ERROR(logger_, "ts_store count: " << ts_store_.count(current_ts_wrap_));
            //LOG4CXX_ERROR(logger_, "Wrap report: " << ts_store_[current_ts_wrap_]->report());
            frames = this->add_jobs_to_buffer(check_for_data_to_write());
            processed_frames_++;
            output_frames_ += frames.size();
        } else {
            // This is an IDLE frame, so we need to completely flush all remaining jobs
            frames = this->add_jobs_to_buffer(purge_remaining_jobs());
            std::vector<boost::shared_ptr<Frame> > purged_frames;
            purged_frames = this->purge_remaining_buffers();
            frames.insert(frames.end(), purged_frames.begin(), purged_frames.end());
            // Now reset all counters
            current_ts_wrap_ = 0;
            current_ts_buffer_ = 0;
            // and the buffers
            timeStampBuffer_->resetFrameNumber();
            idBuffer_->resetFrameNumber();
            energyBuffer_->resetFrameNumber();
            ctrlWordBuffer_->resetFrameNumber();
            ctrlTimeStampBuffer_->resetFrameNumber();
            // Reset the time slice array and counter
            last_written_ts_index_ = 0;
            ts_index_array_.assign(TRISTAN::time_slice_write_size * TRISTAN::number_of_time_slice_buffers, 0);
            // Reset the DAQ format version
            daq_version_ = -1;
        }
        LOG4CXX_DEBUG_LEVEL(2, logger_, "Job stack size: " << jobStack_.size());
        return frames;
    }

    std::vector<boost::shared_ptr<Frame> > TristanProcessCoordinator::add_jobs_to_buffer(std::vector<boost::shared_ptr<TristanProcessJob> > jobs)
    {
        std::vector<boost::shared_ptr<Frame> > frames;
        boost::shared_ptr<Frame> processedFrame;
        LOG4CXX_DEBUG_LEVEL(2, logger_, "Processed packets ready to write out: " << jobs.size());
        // Copy each processed job into the relevant buffer
        std::vector<boost::shared_ptr<TristanProcessJob> >::iterator iter;
        for (iter = jobs.begin(); iter != jobs.end(); ++iter) {
            boost::shared_ptr<TristanProcessJob> job = *iter;
            processedFrame = timeStampBuffer_->appendData(job->event_ts_ptr, job->valid_results);
            if (processedFrame) {
                LOG4CXX_DEBUG_LEVEL(2, logger_, "Pushing timestamp data frame.");
                frames.push_back(processedFrame);
            }

            processedFrame = idBuffer_->appendData(job->event_id_ptr, job->valid_results);
            if (processedFrame) {
                LOG4CXX_DEBUG_LEVEL(2, logger_, "Pushing ID data frame.");
                frames.push_back(processedFrame);
            }

            processedFrame = energyBuffer_->appendData(job->event_energy_ptr, job->valid_results);
            if (processedFrame) {
                LOG4CXX_DEBUG_LEVEL(2, logger_, "Pushing energy data frame.");
                frames.push_back(processedFrame);
            }

            processedFrame = ctrlTimeStampBuffer_->appendData(job->ctrl_word_ts_ptr, job->valid_control_words);
            if (processedFrame) {
                LOG4CXX_DEBUG_LEVEL(2, logger_, "Pushing control word timestamps.");
                frames.push_back(processedFrame);
            }

            processedFrame = ctrlWordBuffer_->appendData(job->ctrl_word_id_ptr, job->valid_control_words);
            if (processedFrame) {
                LOG4CXX_DEBUG_LEVEL(2, logger_, "Pushing control word IDs.");
                frames.push_back(processedFrame);
            }

            // Job is now finished, release it back to the stack
            this->releaseJob(job);
        }
        return frames;
    }

    std::vector<boost::shared_ptr<Frame> > TristanProcessCoordinator::purge_remaining_buffers()
    {
        std::vector<boost::shared_ptr<Frame> > frames;
        boost::shared_ptr<Frame> processedFrame;
        LOG4CXX_DEBUG_LEVEL(2, logger_, "Purging any remaining data from buffers");
        processedFrame = timeStampBuffer_->retrieveCurrentFrame();
        if (processedFrame) {
            LOG4CXX_DEBUG_LEVEL(2, logger_, "Pushing timestamp data frame.");
            frames.push_back(processedFrame);
        }

        processedFrame = idBuffer_->retrieveCurrentFrame();
        if (processedFrame) {
            LOG4CXX_DEBUG_LEVEL(2, logger_, "Pushing ID data frame.");
            frames.push_back(processedFrame);
        }

        processedFrame = energyBuffer_->retrieveCurrentFrame();
        if (processedFrame) {
            LOG4CXX_DEBUG_LEVEL(2, logger_, "Pushing energy data frame.");
            frames.push_back(processedFrame);
        }

        processedFrame = ctrlTimeStampBuffer_->retrieveCurrentFrame();
        if (processedFrame) {
            LOG4CXX_DEBUG_LEVEL(2, logger_, "Pushing control word timestamps.");
            frames.push_back(processedFrame);
        }

        processedFrame = ctrlWordBuffer_->retrieveCurrentFrame();
        if (processedFrame) {
            LOG4CXX_DEBUG_LEVEL(2, logger_, "Pushing control word IDs.");
            frames.push_back(processedFrame);
        }

        return frames;
    }

    void TristanProcessCoordinator::frame_to_jobs(boost::shared_ptr<Frame> frame)
    {
        TRISTAN::PacketHeader packet_header = {};
        const TRISTAN::FrameHeader* hdrPtr = static_cast<const TRISTAN::FrameHeader*>(frame->get_data_ptr());
        // Extract the header words from each packet
        const char *payload_ptr = static_cast<const char*>(frame->get_data_ptr());
        payload_ptr += sizeof(TRISTAN::FrameHeader);
        // Number of packet header 64bit words
        uint16_t packet_header_count = (TRISTAN::packet_header_size / sizeof(uint64_t)) - 1;

        int dropped_packets = 0;
        for (int index = 0; index < TRISTAN::num_primary_packets; index++) {
            if (hdrPtr->packet_state[index] == 0) {
                dropped_packets += 1;
            } else {
                packet_header.headerWord1 = *(((uint64_t *) payload_ptr) + 1);
                packet_header.headerWord2 = *(((uint64_t *) payload_ptr) + 2);

                // Check if this is the correct packet type for processing
                if (TRISTAN::get_packet_mode(packet_header.headerWord1) == TRISTAN::MODE_EVENT) {
                    // We need to decode how many values are in the packet
                    uint32_t packet_number = TRISTAN::get_packet_number(packet_header.headerWord2);
                    uint16_t word_count = TRISTAN::get_word_count(packet_header.headerWord1);
                    uint32_t time_slice = TRISTAN::get_time_slice_id(packet_header.headerWord1,
                                                                   packet_header.headerWord2);
                    uint16_t words_to_process = word_count - packet_header_count;

                    // Check the data version and record it if changed
                    uint8_t data_version = TRISTAN::get_data_format_version(packet_header.headerWord2);
                    if (data_version != daq_version_){
                        daq_version_ = (int32_t)data_version;
                        LOG4CXX_DEBUG_LEVEL(3, logger_, "Publishing data version: " << daq_version_);
                        publish_daq_format_version_meta_data(acq_id_, daq_version_);
                    }

                    uint64_t *data_ptr = (((uint64_t *) payload_ptr) + 1);
                    data_ptr += packet_header_count;
                    boost::shared_ptr <TristanProcessJob> job = this->getJob();
                    job->job_id = (uint32_t) index;
                    job->packet_number = packet_number;
                    job->data_ptr = data_ptr;
                    job->time_slice = time_slice;
                    job->time_slice_wrap = TRISTAN::get_time_slice_modulo(packet_header.headerWord1);
                    job->time_slice_buffer = TRISTAN::get_time_slice_number(packet_header.headerWord2);
                    job->words_to_process = words_to_process;
                    LOG4CXX_DEBUG_LEVEL(3, logger_, "Job number [" << job->job_id
                            << "] TS Wrap [" << job->time_slice_wrap
                            << "] TS Buffer[ " << job->time_slice_buffer
                            << "]: Adding job to processing queue");
                    jobQueue_->add(job, true);
                } else {
                    // Increment the dropped packets counter as we cannot process this invalid packet
                    dropped_packets += 1;
                    // Record the invalid packet as a statistic
                    invalid_packets_ += 1;
                    // Log the invalid packet as an error
                    LOG4CXX_ERROR(logger_, "Invalid packet mode detected. Packet number [" << TRISTAN::get_packet_number(packet_header.headerWord2)
                            << "] TS Wrap [" << TRISTAN::get_time_slice_modulo(packet_header.headerWord1)
                            << "] TS Buffer [" << TRISTAN::get_time_slice_number(packet_header.headerWord2)
                            << "]: Packet marked as a count mode packet");
                }
            }
            payload_ptr += TRISTAN::primary_packet_size;
        }

        std::vector<boost::shared_ptr <TristanProcessJob> > completed_jobs(TRISTAN::num_primary_packets);

        // Place the jobs in order in a vector
        size_t processed_jobs = 0;
        while (processed_jobs + dropped_packets < TRISTAN::num_primary_packets){
            boost::shared_ptr <TristanProcessJob> job = resultsQueue_->remove();
            completed_jobs[job->job_id] = job;
            processed_jobs++;
        }

        // Now we need to reconstruct the full dataset from the individual processing jobs
        std::vector<boost::shared_ptr <TristanProcessJob> >::iterator iter;
        for (iter = completed_jobs.begin(); iter != completed_jobs.end(); ++iter){
            boost::shared_ptr<TristanProcessJob> job = *iter;
            if (job) {
                // Record any timestamp mismatches
                timestamp_mismatches_ += job->timestamp_mismatches;

                // Add the job to the correct time slice wrap object
                if (ts_store_.count(job->time_slice_wrap) > 0) {
                    ts_store_[job->time_slice_wrap]->add_job(job->time_slice_buffer, job);
                    if (job->time_slice_wrap == current_ts_wrap_ && job->time_slice_buffer > current_ts_buffer_) {
                        current_ts_buffer_ = job->time_slice_buffer;
                    }
                } else {
                    // Is this the first packet of a new time slice wrap or the current or previous?
                    uint32_t previous_ts_wrap = current_ts_wrap_;
                    if (previous_ts_wrap > 0) {
                        previous_ts_wrap--;
                    }
                    if (job->time_slice_wrap >= previous_ts_wrap) {
                        // Reset the current time slice buffer to be whatever this job is
                        current_ts_buffer_ = job->time_slice_buffer;
                        // Create the new wrap object and add it to the store
                        boost::shared_ptr <TristanTimeSliceWrap> wrap = boost::shared_ptr<TristanTimeSliceWrap>(
                                new TristanTimeSliceWrap(TRISTAN::number_of_time_slice_buffers));
                        ts_store_[job->time_slice_wrap] = wrap;
                        current_ts_wrap_ = job->time_slice_wrap;
                        // Add the packet to the wrap object
                        wrap->add_job(job->time_slice_buffer, job);
                    } else {
                        // This is a fault condition, we have got a packet from more than 1 wrap in the past
                        // Mark the job as invalid
                        job->invalid = 1;
                        // Log the error
                        LOG4CXX_ERROR(logger_, "Stale packet received TS Wrap[" << job->time_slice_wrap
                                << "] TS Buffer [" << job->time_slice_buffer
                                << "]: Dropping");
                    }
                }
                processed_jobs_++;
                // If the job is marked as invalid then increment the total number of invalid packets
                if (job->invalid > 0){
                    invalid_packets_ += 1;
                }
            }
        }
    }

    std::vector<boost::shared_ptr<TristanProcessJob> > TristanProcessCoordinator::check_for_data_to_write()
    {
        std::vector<boost::shared_ptr<TristanProcessJob> > jobs;
        if (current_ts_wrap_ > 0) {
            // Loop over ts_store_ and return any data from old wraps (more than 1 wrap in the past)
            std::map<uint32_t, boost::shared_ptr<TristanTimeSliceWrap> >::iterator iter;
            for (iter = ts_store_.begin(); iter != ts_store_.end();) {
                // Check for old wraps, return the jobs and delete them
                if (iter->first < current_ts_wrap_ - 1) {
                    // Update the time slice information for this wrap
                    this->update_time_slice_meta_data(iter->first, iter->second->get_all_event_data_counts());

                    // This is two or more wraps in the past, so we can clear it out and then delete it
                    std::vector<boost::shared_ptr<TristanProcessJob> > wrap_jobs = iter->second->empty_all_buffers();
                    jobs.insert(jobs.end(), wrap_jobs.begin(), wrap_jobs.end());
                    ts_store_.erase(iter++);
                } else {
                    ++iter;
                }
            }
        }
        return jobs;
    }

    void TristanProcessCoordinator::update_time_slice_meta_data(uint32_t wrap, std::vector<uint32_t> event_counts)
    {
        // Calculate the base index for the time slice array
        // This is the (wrap number * number of buffers in a wrap) - last written out index
        uint32_t base_index = (wrap * TRISTAN::number_of_time_slice_buffers) - last_written_ts_index_;

        // First check if the new wrap is outside the current ts_index size and publish any updates
        bool publish = true;
        while (base_index >= ts_index_array_.size()){
            // We have got a full time slice array so publish the array and reset it
            if (publish){
                this->publish_time_slice_meta_data(acq_id_, ts_index_array_.size());
            }
            // Update the last written ts_index value
            last_written_ts_index_ += (TRISTAN::time_slice_write_size * TRISTAN::number_of_time_slice_buffers);
            ts_index_array_.assign(TRISTAN::time_slice_write_size * TRISTAN::number_of_time_slice_buffers, 0);
            base_index = (wrap * TRISTAN::number_of_time_slice_buffers) - last_written_ts_index_;
            // There is no point publishing a series of empty time slice entries
            publish = false;
        }

        // Now add the latest wrap counters and publish again if necessary
        for (int index = 0; index < event_counts.size(); index++){
            ts_index_array_[base_index] = event_counts[index];
            base_index++;
            if (base_index == ts_index_array_.size()){
                // We have got a full time slice array so publish the array and reset it
                this->publish_time_slice_meta_data(acq_id_, ts_index_array_.size());
                // Update the last written ts_index value
                last_written_ts_index_ += (TRISTAN::time_slice_write_size * TRISTAN::number_of_time_slice_buffers);
                ts_index_array_.assign(TRISTAN::time_slice_write_size * TRISTAN::number_of_time_slice_buffers, 0);
            }
        }
    }

    void TristanProcessCoordinator::purge_time_slice_meta_data()
    {
        // We only want to purge if there is real data
        if (last_written_ts_index_ > 0) {
            // Publish the current array even if it isn't full and then reset it
            this->publish_time_slice_meta_data(acq_id_, ts_index_array_.size());
            ts_index_array_.assign(TRISTAN::time_slice_write_size * TRISTAN::number_of_time_slice_buffers, 0);
        } else {
            // If the last written index is 0 check if there are any non zero values
            uint32_t sum_of_elems = 0;
            for(std::vector<uint32_t>::iterator it = ts_index_array_.begin(); it != ts_index_array_.end(); ++it){
                sum_of_elems += *it;
            }
            // If there are non zero elements then this must be a valid array of indexes so publish the meta data
            if (sum_of_elems > 0) {
                this->publish_time_slice_meta_data(acq_id_, ts_index_array_.size());
                ts_index_array_.assign(TRISTAN::time_slice_write_size * TRISTAN::number_of_time_slice_buffers, 0);
            }
        }
    }

    void TristanProcessCoordinator::publish_daq_format_version_meta_data(const std::string& acq_id, int32_t version)
    {
        if (metaPtr_){
            rapidjson::Document meta_document;
            meta_document.SetObject();

            // Add Acquisition ID
            rapidjson::Value key_acq_id("acqID", meta_document.GetAllocator());
            rapidjson::Value value_acq_id;
            value_acq_id.SetString(acq_id.c_str(), acq_id.size(), meta_document.GetAllocator());
            meta_document.AddMember(key_acq_id, value_acq_id, meta_document.GetAllocator());
            // Add rank
            rapidjson::Value key_rank("rank", meta_document.GetAllocator());
            rapidjson::Value value_rank;
            value_rank.SetInt(rank_);
            meta_document.AddMember(key_rank, value_rank, meta_document.GetAllocator());

            rapidjson::StringBuffer buffer;
            rapidjson::Writer<rapidjson::StringBuffer> writer(buffer);
            meta_document.Accept(writer);

            LOG4CXX_DEBUG_LEVEL(3, logger_, "Publishing daq format version meta data");
            metaPtr_->publish_meta("tristan",
                                   "daq_version",
                                   &version,
                                   sizeof(int32_t),
                                   buffer.GetString());
        }
    }

    void TristanProcessCoordinator::publish_time_slice_meta_data(const std::string& acq_id, uint32_t qty_of_ts)
    {
        if (metaPtr_){
            rapidjson::Document meta_document;
            meta_document.SetObject();

            // Add Acquisition ID
            rapidjson::Value key_acq_id("acqID", meta_document.GetAllocator());
            rapidjson::Value value_acq_id;
            value_acq_id.SetString(acq_id.c_str(), acq_id.size(), meta_document.GetAllocator());
            meta_document.AddMember(key_acq_id, value_acq_id, meta_document.GetAllocator());
            // Add rank
            rapidjson::Value key_rank("rank", meta_document.GetAllocator());
            rapidjson::Value value_rank;
            value_rank.SetInt(rank_);
            meta_document.AddMember(key_rank, value_rank, meta_document.GetAllocator());
            // Add number of data points
            rapidjson::Value key_qty("qty", meta_document.GetAllocator());
            rapidjson::Value value_qty;
            value_qty.SetInt(qty_of_ts);
            meta_document.AddMember(key_qty, value_qty, meta_document.GetAllocator());
            // Add ts index
            rapidjson::Value key_index("index", meta_document.GetAllocator());
            rapidjson::Value value_index;
            value_index.SetInt(last_written_ts_index_);
            meta_document.AddMember(key_index, value_index, meta_document.GetAllocator());

            rapidjson::StringBuffer buffer;
            rapidjson::Writer<rapidjson::StringBuffer> writer(buffer);
            meta_document.Accept(writer);

            LOG4CXX_DEBUG_LEVEL(3, logger_, "Publishing time slice meta data: " << buffer.GetString());
            metaPtr_->publish_meta("tristan",
                                   "time_slice",
                                   ts_index_array_.data(),
                                   qty_of_ts * sizeof(uint32_t),
                                   buffer.GetString());
        }
    }

    std::vector<boost::shared_ptr<TristanProcessJob> > TristanProcessCoordinator::purge_remaining_jobs()
    {
        std::vector<boost::shared_ptr<TristanProcessJob> > jobs;
        // Loop over ts_store_ and return any data from old wraps (more than 1 wrap in the past)
        std::map<uint32_t, boost::shared_ptr<TristanTimeSliceWrap> >::iterator iter;
        for (iter = ts_store_.begin(); iter != ts_store_.end(); ++iter) {
            // Update the time slice information for this wrap
            this->update_time_slice_meta_data(iter->first, iter->second->get_all_event_data_counts());

            std::vector<boost::shared_ptr<TristanProcessJob> > wrap_jobs = iter->second->empty_all_buffers();
            jobs.insert(jobs.end(), wrap_jobs.begin(), wrap_jobs.end());
//            ts_store_.erase(iter);
        }
        ts_store_.clear();

        // Purge any remaining time slice information
        this->purge_time_slice_meta_data();
        return jobs;
    }

  void TristanProcessCoordinator::processTask()
  {
      LOG4CXX_TRACE(logger_, "Starting processing task with ID [" << boost::this_thread::get_id() << "]");
      bool executing = true;
      uint16_t max_number_of_words = (TRISTAN::primary_packet_size / sizeof(uint64_t));
      while (executing){
          boost::shared_ptr<TristanProcessJob> job = jobQueue_->remove();
          job->valid_results = 0;
          job->valid_control_words = 0;
          job->timestamp_mismatches = 0;
          uint64_t previous_course_timestamp = 0;
          uint64_t current_course_timestamp = 0;
          uint64_t *data_word_ptr = job->data_ptr;
          uint64_t *event_ts_ptr = job->event_ts_ptr;
          uint32_t *event_id_ptr = job->event_id_ptr;
          uint32_t *event_energy_ptr = job->event_energy_ptr;
          uint64_t *ctrl_word_ts_ptr = job->ctrl_word_ts_ptr;
          uint16_t *ctrl_word_id_ptr = job->ctrl_word_id_ptr;
          uint32_t *ctrl_index_ptr = job->ctrl_index_ptr;
          // Verify the first word is an extended timestamp word
          if (TRISTAN::get_control_type(*data_word_ptr) != TRISTAN::ExtendedTimestamp){
              // Mark the job as invalid
              job->invalid = 1;
              // Log the error
              LOG4CXX_ERROR(logger_, "Error in job [" << job->job_id
                      << "] TS Wrap [" << job->time_slice_wrap
                      << "] TS Buffer [" << job->time_slice_buffer
                      << "]: The first word is not an extended timestamp");
          }
          if (job->words_to_process <= max_number_of_words) {
              for (uint16_t index = 0; index < job->words_to_process; index++) {
                  uint32_t mismatch = 0;
                  if (processDataWord(*data_word_ptr,
                                      &previous_course_timestamp,
                                      &current_course_timestamp,
                                      job->packet_number,
                                      job->time_slice_wrap,
                                      job->time_slice_buffer,
                                      event_ts_ptr,
                                      event_id_ptr,
                                      event_energy_ptr,
                                      &mismatch)) {
                      // Check for a timestamp mismatch
                      if (mismatch == 1) {
                          // Record the mismatch, do not increase event pointers
                          job->timestamp_mismatches++;
                      } else {
                          // Increment the event ptrs and the valid result count
                          event_ts_ptr++;
                          event_id_ptr++;
                          event_energy_ptr++;
                          job->valid_results++;
                      }
                  } else if (TRISTAN::is_control_word(*data_word_ptr)) {
                      // Set the control word timestamp value
                      *ctrl_word_ts_ptr = *data_word_ptr & TRISTAN::course_timestamp_mask;
                      // Set the control word id value
                      *ctrl_word_id_ptr = (uint16_t)((*data_word_ptr & TRISTAN::control_word_full_mask) >> 52);
                      // Set the index value for the control word
                      *ctrl_index_ptr = job->valid_results;
                      // Increment the control pointers and the valid result count
                      ctrl_word_ts_ptr++;
                      ctrl_word_id_ptr++;
                      ctrl_index_ptr++;
                      job->valid_control_words++;
                  } else {
                      LOG4CXX_ERROR(logger_, "Unknown word type [" << *data_word_ptr << "]");
                  }
                  data_word_ptr++;
              }
          } else {
              // Mark the job as invalid
              job->invalid = 1;
              // Log the issue
              LOG4CXX_ERROR(logger_, "Could not process job [" << job->job_id
                      << "] TS Wrap [" << job->time_slice_wrap
                      << "] TS Buffer [" << job->time_slice_buffer
                      << "]: Invalid number of words to process => " << job->words_to_process);
          }
          LOG4CXX_DEBUG_LEVEL(2, logger_, "Processing complete for job [" << job->job_id
                  << "] on task [" << boost::this_thread::get_id()
                  << "] : Number of valid results [" << job->valid_results
                  << "] : Number of mismatches [" << job->timestamp_mismatches << "]");
          resultsQueue_->add(job, true);
      }
  }

  boost::shared_ptr<TristanProcessJob> TristanProcessCoordinator::getJob()
  {
      boost::shared_ptr<TristanProcessJob> job;
      // Check if we have a job available
      if (jobStack_.size() > 0){
          job = jobStack_.top();
          jobStack_.pop();
      } else{
          // No job available so create a new one
          job = boost::shared_ptr<TristanProcessJob>(new TristanProcessJob(TRISTAN::primary_packet_size/sizeof(uint64_t)));
      }
      return job;
  }

  void TristanProcessCoordinator::releaseJob(boost::shared_ptr<TristanProcessJob> job)
  {
      // Reset the job
      job->reset();
      // Place the job back on the stack ready for re-use
      jobStack_.push(job);
  }

  bool TristanProcessCoordinator::processDataWord(uint64_t data_word,
                                                uint64_t *previous_course_timestamp,
                                                uint64_t *current_course_timestamp,
                                                uint32_t packet_number,
                                                uint32_t time_slice_wrap,
                                                uint32_t time_slice_buffer,
                                                uint64_t *event_ts,
                                                uint32_t *event_id,
                                                uint32_t *event_energy,
                                                uint32_t *mismatch)
  {
      bool event_word = false;
      //LOG4CXX_DEBUG(logger_, "Data Word: 0x" << std::hex << data_word);
      if (TRISTAN::is_control_word(data_word)){
          if (TRISTAN::get_control_type(data_word) == TRISTAN::ExtendedTimestamp){
              uint64_t ts = getCourseTimestamp(data_word);
//              LOG4CXX_DEBUG(logger_, "Parsing extended timestamp control word [" << std::hex << data_word << "] value [" << std::dec << ts << "]");
              // Register the timestamp with the manager
//              ts_manager_.add_timestamp(time_slice_buffer, time_slice_wrap, packet_number, (ts & TRISTAN::timestamp_match_mask));
              *previous_course_timestamp = *current_course_timestamp;
              *current_course_timestamp = ts;
              if (*previous_course_timestamp == 0){
                  // Calculate the previous course timestamp by subtracting the delta from the current
                  *previous_course_timestamp = *current_course_timestamp - TRISTAN::course_timestamp_rollover; //ts_manager_.read_delta();
                  //LOG4CXX_DEBUG(logger_, "**** Current course timestamp [" << std::dec << *current_course_timestamp << "]");
                  //LOG4CXX_DEBUG(logger_, "**** Previous course timestamp calculated from TS manager [" << std::dec << *previous_course_timestamp << "]");
              }
//			LOG4CXX_DEBUG(logger_, "New extended timestamp [" << std::dec << *current_course_timestamp << "]");
          }
      } else {
          *event_ts = getFullTimestamp(data_word, *previous_course_timestamp, *current_course_timestamp, mismatch);
          *event_energy = getEnergy(data_word);
          *event_id = getPositionID(data_word);
//          *event_ts = packet_number;
//          *event_energy = time_slice_wrap;
//          *event_id = time_slice_buffer;
          event_word = true;
      }
      return event_word;
  }

  uint64_t TristanProcessCoordinator::getCourseTimestamp(uint64_t data_word)
  {
      if (!TRISTAN::is_control_word(data_word)){
          throw TristanProcessingException("Data word is not a control word");
      }
      return data_word & TRISTAN::course_timestamp_mask;
  }

  uint64_t TristanProcessCoordinator::getFineTimestamp(uint64_t data_word)
  {
      if (TRISTAN::is_control_word(data_word)){
          throw TristanProcessingException("Data word is a control word, not an event");
      }
      return (data_word >> 14) & TRISTAN::fine_timestamp_mask;
  }

  uint16_t TristanProcessCoordinator::getEnergy(uint64_t data_word)
  {
      if (TRISTAN::is_control_word(data_word)){
          throw TristanProcessingException("Data word is a control word, not an event");
      }
      return data_word & TRISTAN::energy_mask;
  }

  uint32_t TristanProcessCoordinator::getPositionID(uint64_t data_word)
  {
      if (TRISTAN::is_control_word(data_word)){
          throw TristanProcessingException("Data word is a control word, not an event");
      }
      return (data_word >> 37) & TRISTAN::position_mask;
  }

  uint64_t TristanProcessCoordinator::getFullTimestamp(uint64_t data_word, uint64_t prev_course, uint64_t course, uint32_t *mismatch)
  {
      uint64_t full_ts = 0;
      uint64_t fine_ts = 0;
      uint64_t next_ts = course + TRISTAN::course_timestamp_rollover;
      *mismatch = 0;
      if (TRISTAN::is_control_word(data_word)){
          throw TristanProcessingException("Data word is a control word, not an event");
      }
      fine_ts = getFineTimestamp(data_word);
      if ((findTimestampMatch(course) == findTimestampMatch(fine_ts)) || (findTimestampMatch(course)+1 == findTimestampMatch(fine_ts))){
          full_ts = (course & TRISTAN::timestamp_match_mask) + fine_ts;
      } else if ((findTimestampMatch(prev_course) == findTimestampMatch(fine_ts)) || (findTimestampMatch(prev_course)+1 == findTimestampMatch(fine_ts))){
          full_ts = (prev_course & TRISTAN::timestamp_match_mask) + fine_ts;
      } else if ((findTimestampMatch(next_ts) == findTimestampMatch(fine_ts)) || (findTimestampMatch(next_ts)+1 == findTimestampMatch(fine_ts))){
          full_ts = (next_ts & TRISTAN::timestamp_match_mask) + fine_ts;
      } else {
          // This is a timestamp mismatch, set the mismatch flag to notify the caller
          *mismatch = 1;
      }
      return full_ts;
  }

  uint8_t TristanProcessCoordinator::findTimestampMatch(uint64_t time_stamp)
  {
      // This method will return the 2 bits required for
      // matching a course timestamp to an extended timestamp
      return (time_stamp >> 21) & 0x03;
  }


}
