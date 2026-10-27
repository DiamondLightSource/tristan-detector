//
// Created by gnx91527 on 17/09/18.
//

#ifndef TRISTAN_TRISTANTIMESLICEWRAP_H
#define TRISTAN_TRISTANTIMESLICEWRAP_H

#include <log4cxx/logger.h>
#include <log4cxx/basicconfigurator.h>
#include <log4cxx/propertyconfigurator.h>
#include <log4cxx/helpers/exception.h>

using namespace log4cxx;
using namespace log4cxx::helpers;

#include <boost/shared_ptr.hpp>

#include <stdlib.h>
#include <stdint.h>
#include <map>

#include "TristanExceptions.h"
#include "TristanTimeSliceBuffer.h"

namespace FrameProcessor {

  class TristanTimeSliceWrap
  {
  public:
    TristanTimeSliceWrap(uint32_t no_of_buffers);
    virtual ~TristanTimeSliceWrap();
    void add_job(uint32_t buffer_no, boost::shared_ptr<TristanProcessJob> job);
    std::vector<boost::shared_ptr<TristanProcessJob> > empty_all_buffers();
    std::vector<boost::shared_ptr<TristanProcessJob> > empty_buffer(uint32_t buffer_number);
    std::vector<uint32_t> get_all_event_data_counts();
    uint32_t get_event_data_counts(uint32_t buffer_number);
    std::string report();

  private:
    /** Pointer to logger */
    LoggerPtr logger_;
    uint32_t number_of_buffers_;

    std::map<uint32_t, boost::shared_ptr<TristanTimeSliceBuffer> > buffer_store_;
  };


}

#endif //TRISTAN_TRISTANTIMESLICEWRAP_H
