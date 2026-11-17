//
// Created by gnx91527 on 31/07/18.
//

#ifndef TRISTAN_TRISTANTIMESTAMPMANAGER_H
#define TRISTAN_TRISTANTIMESTAMPMANAGER_H

#include <log4cxx/logger.h>
#include <log4cxx/basicconfigurator.h>
#include <log4cxx/propertyconfigurator.h>
#include <log4cxx/helpers/exception.h>

#include <boost/thread.hpp>

using namespace log4cxx;
using namespace log4cxx::helpers;

#include <stdlib.h>
#include <stdint.h>
#include <map>

namespace FrameProcessor {
    //! TristanTimestampException - custom exception class implementing "what" for error string
    class TristanTimestampException : public std::exception {
    public:

        //! Create TristanTimestampException with no message
        TristanTimestampException(void) throw() :
                what_("") {};

        //! Creates TristanTimestampException with informational message
        TristanTimestampException(const std::string what) throw() :
                what_(what) {};

        //! Returns the content of the informational message
        virtual const char *what(void) const throw() {
            return what_.c_str();
        };

        //! Destructor
        ~TristanTimestampException(void) throw() {};

    private:

        // Member variables
        const std::string what_;  //!< Informational message about the exception

    }; // TristanTimestampException

    class TristanTimestampManager {
    public:
        TristanTimestampManager();

        virtual ~TristanTimestampManager();

        void clear();

        void reset_delta();

        void add_timestamp(uint32_t time_slice_buffer,
                           uint32_t time_slice_wrap,
                           uint32_t packet_number,
                           uint64_t timestamp);

        uint64_t read_delta();

    private:
        /** Pointer to logger */
        LoggerPtr logger_;

        /** Mutex used to make this class thread safe */
        boost::recursive_mutex mutex_;

        std::map <uint32_t, uint64_t> timestamps_;
        uint64_t delta_timestamp_;
        uint32_t time_slice_buffer_;
        uint32_t time_slice_wrap_;
    };


}

#endif //TRISTAN_TRISTANTIMESTAMPMANAGER_H
