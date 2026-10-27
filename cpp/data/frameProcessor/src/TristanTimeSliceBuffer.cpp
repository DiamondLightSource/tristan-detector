//
// Created by gnx91527 on 17/09/18.
//
#include "TristanTimeSliceBuffer.h"
#include "DebugLevelLogger.h"
#include <stdio.h>
namespace FrameProcessor {

TristanTimeSliceBuffer::TristanTimeSliceBuffer() :
    no_of_events_(0)
{
  // Setup logging for the class
  logger_ = Logger::getLogger("FP.TristanTimeSliceBuffer");
  logger_->setLevel(Level::getAll());
  LOG4CXX_DEBUG_LEVEL(2, logger_, "TristanTimeSliceBuffer constructor.");
}

TristanTimeSliceBuffer::~TristanTimeSliceBuffer()
{
  job_store_.clear();
}

void TristanTimeSliceBuffer::add_job(boost::shared_ptr<TristanProcessJob> job)
{
  // Verify that the packet ID does not already exist within this buffer
  if (job_store_.count(job->packet_number) > 0){
    LOG4CXX_ERROR(logger_, "Duplicate packet detected for packet ID [" << job->packet_number << "] TS Wrap ["	<< job->time_slice_wrap << "] TS Buffer [" << job->time_slice_buffer << "]");
    throw TristanProcessingException("Duplicate packet ID for the same time slice");
  } else {
    job_store_[job->packet_number] = job;
    no_of_events_ += job->valid_results;
  }
}

std::vector<boost::shared_ptr<TristanProcessJob> > TristanTimeSliceBuffer::empty()
{
  std::vector<boost::shared_ptr<TristanProcessJob> > jobs;
  std::map<uint32_t, boost::shared_ptr<TristanProcessJob> >::iterator iter;
  for (iter = job_store_.begin(); iter != job_store_.end(); ++iter){
    jobs.push_back(iter->second);
  }
  job_store_.clear();
  no_of_events_ = 0;
  return jobs;
}

size_t TristanTimeSliceBuffer::size()
{
  return job_store_.size();
}

uint32_t TristanTimeSliceBuffer::no_of_events()
{
  return no_of_events_;
}

std::string TristanTimeSliceBuffer::report()
{
  // Print a full report of wrap object
  std::stringstream ss;
  ss << "***  => Number of packets stored: " << job_store_.size() << "\n" << "***  => ";
  std::map<uint32_t, boost::shared_ptr<TristanProcessJob> >::iterator iter;
  int counter = 0;
  for (iter = job_store_.begin(); iter != job_store_.end(); ++iter){
    ss << iter->first << ", ";
    counter++;
    if (counter % 10 == 0){
      ss << "\n***  => ";
    }
  }
  ss << "\n";
  return ss.str();
}

}
