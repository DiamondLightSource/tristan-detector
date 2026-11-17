//
// Created by gnx91527 on 17/09/18.
//

#ifndef TRISTAN_TRISTANTIMESLICEBUFFER_H
#define TRISTAN_TRISTANTIMESLICEBUFFER_H

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
#include "TristanProcessJob.h"

namespace FrameProcessor {

  class TristanTimeSliceBuffer
  {
  public:
    TristanTimeSliceBuffer();
    virtual ~TristanTimeSliceBuffer();
    void add_job(boost::shared_ptr<TristanProcessJob> job);
    std::vector<boost::shared_ptr<TristanProcessJob> > empty();
    size_t size();
    uint32_t no_of_events();
    std::string report();

  private:
    /** Pointer to logger */
    LoggerPtr logger_;

    std::map<uint32_t, boost::shared_ptr<TristanProcessJob> > job_store_;

    uint32_t no_of_events_;
  };


}

#endif //TRISTAN_TRISTANTIMESLICEBUFFER_H
