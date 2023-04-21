//
// Created by gnx91527 on 27/09/18.
//

#ifndef LATRD_LATRDIMAGEJOB_H
#define LATRD_LATRDIMAGEJOB_H

#include "DataBlockFrame.h"

#include <boost/shared_ptr.hpp>
#include "DebugLevelLogger.h"

#include <stdlib.h>
#include <stdint.h>
#include <vector>


namespace FrameProcessor {

    class LATRDImage
    {
    public:
      LATRDImage(uint32_t width, uint32_t height, uint32_t number);
      virtual ~LATRDImage();
      void set_eoi(uint32_t packet_id);
      uint32_t get_frame_number();

      inline void add_pixel(uint32_t x, uint32_t y, uint32_t event_count)
      {
        uint32_t data_index = x + (y * width_);
        // we could have X,Y individual bounds checks, but this is faster.
        if(__builtin_expect(data_index < image_qty_, 1))
        {
          image_ptr_[data_index] += (uint16_t)event_count;
        }
        else
        {
          LOG4CXX_ERROR(logger_, "Pixel position out of range: " << x << "," << y << " should be less than " << width_ << "," << height_);
        }
      }

      void set_packet_seen(uint32_t packet_id);
      bool verify_image();
      boost::shared_ptr<Frame> to_frame();

      void mark_sent();
      bool get_sent();

    private:
      void reset(uint32_t width, uint32_t height);

      uint32_t width_;
      uint32_t height_;
      uint32_t image_number_;
      uint16_t* image_ptr_;
      // this is the number of pixels in the image so we don't have to calculate w*h.
      uint32_t image_qty_;
      boost::shared_ptr<DataBlockFrame> out_frame_;
      uint64_t timestamp_;
      bool sent_;
      std::map<uint32_t, uint32_t> packet_ids_;
      int32_t eoi_packet_id_;
      log4cxx::LoggerPtr logger_;
    };

} /* namespace FrameProcessor */

#endif //LATRD_LATRDIMAGEJOB_H
