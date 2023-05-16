//
// Created by gnx91527 on 06/08/18.
//
#include "LATRDDefinitions.h"
#include "LATRDProcessIntegral.h"
#include "LATRDExceptions.h"
#include "DebugLevelLogger.h"

namespace FrameProcessor {
  LATRDProcessIntegral::LATRDProcessIntegral() :
      width_(0),
      height_(0),
      total_count_(0),
      next_frame_id_(1),
      next_packet_id_(0)
  {
    // Setup logging for the class
    logger_ = Logger::getLogger("FP.LATRDProcessIntegral");
    LOG4CXX_TRACE(logger_, "LATRDProcessIntegral constructor.");

  }

  LATRDProcessIntegral::~LATRDProcessIntegral()
  {
  }

  void LATRDProcessIntegral::init(uint32_t width, uint32_t height) {
    width_ = width;
    height_ = height;
    next_frame_id_ = 1;
    next_packet_id_ = 0;

    LOG4CXX_DEBUG_LEVEL(0, logger_, "width, height set to " << width << "," << height);
    reset_image();
  }

  void LATRDProcessIntegral::reset_image()
  {
    LOG4CXX_DEBUG_LEVEL(2, logger_, "Resetting");

    total_count_ = 0;
  }

  std::vector<boost::shared_ptr<Frame> > LATRDProcessIntegral::process_frame(boost::shared_ptr <Frame> frame)
  {
    std::vector<boost::shared_ptr<Frame> > out_frames;

    // Extract the header from the buffer and print the details
    const LATRD::FrameHeader *hdrPtr = static_cast<const LATRD::FrameHeader *>(frame->get_data_ptr());

    // Test for idle frames.
    if (hdrPtr->idle_frame == 1){
      LOG4CXX_DEBUG_LEVEL(3, logger_, "Count mode IDLE frame detected");

      // This is an idle frame
      // First we need to process any outstanding image frames, and then reset the image counter
      std::map<uint64_t, boost::shared_ptr<LATRDImage> >::iterator iter;
      for (iter = image_store_.begin(); iter != image_store_.end(); ++iter){
          if (iter->second->get_sent()==false) {
            LOG4CXX_DEBUG_LEVEL(2, logger_,
                          "Creating image frame " << iter->second->get_frame_number() << " from raw buffer " << frame->get_frame_number());
            boost::shared_ptr<Frame> out_frame = iter->second->to_frame();
            out_frames.push_back(out_frame);

            iter->second->mark_sent();
          }
      }
      image_store_.clear();

      // and reset the expected frame ID
      next_frame_id_ = 1;

    } else {
      // note that the use of frame_to_image is single-threaded
      out_frames = frame_to_image(frame);
    }
    return out_frames;
  }

  std::vector<boost::shared_ptr<Frame> > LATRDProcessIntegral::frame_to_image(boost::shared_ptr <Frame> frame)
  {
    std::vector<boost::shared_ptr<Frame> > image_frames;
    LATRD::PacketHeader packet_header;
    // Extract the header from the buffer and print the details
    const LATRD::FrameHeader *hdrPtr = static_cast<const LATRD::FrameHeader *>(frame->get_data_ptr());

    // Extract the header words from each packet
    uint8_t *payload_ptr = (uint8_t *)(frame->get_data_ptr()) + sizeof(LATRD::FrameHeader);
    // Number of packet header 64bit words
    uint16_t packet_header_count = (LATRD::packet_header_size / sizeof(uint64_t)) - 1;

    int dropped_packets = 0;
    // Loop over each packet
    for (int index = 0; index < LATRD::num_primary_packets; index++) {
      uint32_t bad_packet = 0;
      // Ignore first header word as it is not used.
      packet_header.headerWord1 = *(((uint64_t *) payload_ptr) + 1);
      packet_header.headerWord2 = *(((uint64_t *) payload_ptr) + 2);

      if (hdrPtr->packet_state[index] == 0) {
        dropped_packets += 1;
      } else {
        // Check if this is the correct packet type for image construction
        if (LATRD::get_packet_mode(packet_header.headerWord1) == LATRD::MODE_COUNT) {

          // Walk through each data word
          uint16_t word_count = LATRD::get_word_count(packet_header.headerWord1);
          uint32_t packet_id = LATRD::get_packet_number(packet_header.headerWord2);
          uint32_t image_number = LATRD::get_image_number(packet_header.headerWord2);
          // Ignore the first 0x00000000 which is not used
          uint64_t *data_word_ptr = (((uint64_t *) payload_ptr) + 1 + packet_header_count);

          uint64_t packet_timestamp = 0;
          try {
            packet_timestamp = get_course_timestamp(*data_word_ptr);
          } catch (...) {
            // Caught an exception whilst reading the course timestamp so dump the packet header
            LOG4CXX_ERROR(logger_,
                          "Caught ERROR whilst decoding a count mode packet: Could not retrieve course timestamp");
            std::stringstream ss1;
            ss1 << std::hex << std::setfill('0');
            ss1 << " 0x" << std::setw(16) << packet_header.headerWord1;
            LOG4CXX_ERROR(logger_, "Header 1: " << ss1.str());
            std::stringstream ss2;
            ss2 << std::hex << std::setfill('0');
            ss2 << " 0x" << std::setw(16) << packet_header.headerWord2;
            LOG4CXX_ERROR(logger_, "Header 2: " << ss2.str());
            std::stringstream ss3;
            ss3 << std::hex << std::setfill('0');
            ss3 << " 0x" << std::setw(16) << *data_word_ptr;
            LOG4CXX_ERROR(logger_, "Tmstamp : " << ss3.str());
            bad_packet = 1;
          }

          if (!bad_packet) {
            LOG4CXX_DEBUG_LEVEL(2, logger_,
                          "Image [" << image_number << "] Pkt [" << packet_id << "] timestamp [" << packet_timestamp << "] word count " << word_count);
            data_word_ptr++;

            // Check if we have an image job for this packet's image number
            boost::shared_ptr <LATRDImage> image_job_ptr;
            if (image_store_.count(image_number) > 0) {
              LOG4CXX_DEBUG_LEVEL(2, logger_, "Image [" << image_number << "] found in store");
              image_job_ptr = image_store_[image_number];
            } else {
              // We need to create a new image job for this packet
              LOG4CXX_DEBUG_LEVEL(2, logger_, "First packet for image job [" << image_number << "] creating ImageJob object");
              // TODO: Check this is not an old packet
              image_job_ptr = boost::shared_ptr<LATRDImage>(new LATRDImage(width_, height_, image_number));
              // Store the image job in the store, index by timestamp
              image_store_[image_number] = image_job_ptr;
            }

            image_job_ptr->set_packet_seen(packet_id);
            // Start from index 3 as we can ignore the header words and extended timestamp
            for (uint16_t index = 3; index < word_count; index++) {
              uint32_t x_pos = 0;
              uint32_t y_pos = 0;
              uint32_t i_tot = 0;
              uint32_t event_count = 0;
              uint32_t e_tot = 0;
              try {
                // Check if the word is a final packet word
                if (check_for_final_packet_word(*data_word_ptr)) {
                  LOG4CXX_DEBUG_LEVEL(2, logger_, "Image [" << image_number << "] End Of Image on packet [" << packet_id << "]");
                  image_job_ptr->set_eoi(packet_id);
                } else {
                  if (process_data_word(*data_word_ptr,
                                        &x_pos,
                                        &y_pos,
                                        &i_tot,
                                        &event_count)) {
                    // Add the event count to the 2D image
                    LOG4CXX_DEBUG_LEVEL(4, logger_, "incrementing pixel at " <<  x_pos-origin_x_ << " " <<  y_pos-origin_y_ << " by " << event_count);
                    image_job_ptr->add_pixel(x_pos-origin_x_, y_pos-origin_y_, event_count);
                    total_count_ += event_count;
                  }
                  else
                  {
                    LOG4CXX_DEBUG_LEVEL(4, logger_, "found a non-integral data word");
                  }
                }
              }
              catch (LATRDProcessingException &ex) {
                // TODO: What to do here if there is an exception
              }
              data_word_ptr++;
            }
          }
        } else {
          dropped_packets += 1;
          LOG4CXX_ERROR(logger_, "Invalid packet mode detected! Packet marked as event mode");
        }
      }
      // Increment the payload pointer to the next packet
      payload_ptr += LATRD::primary_packet_size;
    }
    // After processing all of the packets, loop through the job map and see if we can pass out any frames
    std::vector<uint64_t> delete_image_ids;
    std::map<uint64_t, boost::shared_ptr<LATRDImage> >::iterator iter;
    for (iter = image_store_.begin(); iter != image_store_.end(); ++iter){
        if (iter->second->verify_image()){
          if (!iter->second->get_sent()) {
            boost::shared_ptr<Frame> out_frame = iter->second->to_frame();
            LOG4CXX_DEBUG_LEVEL(2, logger_,
                          "Pushing frame for image #" << iter->second->get_frame_number());
            image_frames.push_back(out_frame);

            iter->second->mark_sent();
          }
          // Mark the frame for deletion; this can be done here but isn't.
          delete_image_ids.push_back(iter->first);
        }
    }
    std::vector<uint64_t>::iterator del_iter;
    for (del_iter = delete_image_ids.begin(); del_iter != delete_image_ids.end(); ++del_iter){
      image_store_.erase(*del_iter);
    }

    return image_frames;
  }

  inline bool LATRDProcessIntegral::process_data_word(uint64_t data_word,
                                               uint32_t *chip_x,
                                               uint32_t *chip_y,
                                               uint32_t *i_tot,
                                               uint32_t *event_count)
  {
    if (check_for_integral_data_word(data_word)){
      // Extract the information from the data word
      *chip_x = (uint32_t)((data_word&integral_chip_x_mask)>>37);
      *chip_y = (uint32_t)((data_word&integral_chip_y_mask)>>24);
      *i_tot = (uint32_t)((data_word&integral_i_tot_mask)>>10);
      *event_count = (uint32_t)(data_word&integral_evt_count_mask);
      return true;
    }
    return false;
  }

  bool LATRDProcessIntegral::process_control_word(uint64_t ctrl_word)
  {
    return false;
  }

  uint64_t LATRDProcessIntegral::get_course_timestamp(uint64_t data_word)
  {
    if (!LATRD::is_control_word(data_word)){
      throw LATRDProcessingException("Data word is not a control word");
    }
    return data_word & LATRD::course_timestamp_mask;
  }

  bool LATRDProcessIntegral::check_for_final_packet_word(uint64_t data_word)
  {
    if ((data_word & integral_final_packet_mask) == integral_final_packet_value){
      return true;
    }
    return false;
  }

  bool LATRDProcessIntegral::check_for_integral_data_word(uint64_t data_word)
  {
    if ((data_word & integral_data_word_mask) == integral_data_word_value){
      return true;
    }
    return false;
  }

  void LATRDProcessIntegral::set_origin(int x, int y)
  {
    origin_x_ = x;
    origin_y_ = y;
    LOG4CXX_DEBUG_LEVEL(0, logger_,
                          "Origin set to [" << origin_x_ << "," << origin_y_ << "]");
  }
}
