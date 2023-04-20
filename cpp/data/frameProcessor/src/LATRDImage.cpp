//
// Created by gnx91527 on 27/09/18.
//
#include "LATRDImage.h"
#include "FrameMetaData.h"

namespace FrameProcessor {

    LATRDImage::LATRDImage(uint32_t width, uint32_t height, uint32_t number)
    {
      logger_ = Logger::getLogger("FP.LATRDImage");
      this->reset(width, height);
      image_number_ = number;
      LOG4CXX_DEBUG_LEVEL(2, logger_, "creating LATRD buffer for frame #" << image_number_);
    }

    LATRDImage::~LATRDImage()
    {
      LOG4CXX_DEBUG_LEVEL(2, logger_, "destroying LATRD buffer for frame #" << image_number_);
    }

    void LATRDImage::reset(uint32_t width, uint32_t height)
    {
      FrameMetaData frame_meta;
      width_ = width;
      height_ = height;
      uint32_t size_of_image = width_ * height_ * sizeof(uint16_t);
      out_frame_.reset(new DataBlockFrame(frame_meta, size_of_image));
      // get_image_ptr returns a void*.
      image_ptr_ = static_cast<uint16_t*>(out_frame_->get_image_ptr());
      // We need to zero the memory block
      memset(image_ptr_, 0, size_of_image);
      // Reset the largest_packet_id
      eoi_packet_id_ = -1;
      // Reset the packet id map
      packet_ids_.clear();
      // Reset the sent flag
      sent_ = false;

      image_number_ = 0;
    }

    void LATRDImage::set_eoi(uint32_t packet_id)
    {
        eoi_packet_id_ = (int32_t)packet_id;
    }

    uint32_t LATRDImage::get_frame_number()
    {
        return image_number_;
    }

    void LATRDImage::set_packet_seen(uint32_t packet_id)
    {
      packet_ids_[packet_id] = 1;
    }

    bool LATRDImage::verify_image()
    {
        bool verified = true;

        // First check to see if we have received an EOI packet
        if (eoi_packet_id_ == -1){
            // We have not, so we are not verified
            verified = false;
        }
        if (verified){
          // Loop over the packet IDs and check there are no gaps
          for (uint32_t index = 0; index < eoi_packet_id_; index++){
            if (packet_ids_.count(index) == 0){
              verified = false;
              LOG4CXX_DEBUG_LEVEL(0, logger_, "image " << image_number_ << " is missing packet #" << index << " of " << eoi_packet_id_ << "; keep it.");
              break;
            }
          }
        }
      return verified;
    }

    boost::shared_ptr<Frame> LATRDImage::to_frame()
    {
      // Create the frame object to wrap the image
  		// Create and populate metadata for the re-ordered frame
      FrameMetaData frame_meta;
      std::vector<dimsize_t> dims;
      dims.push_back(height_);
      dims.push_back(width_);
      frame_meta.set_dimensions(dims);
      frame_meta.set_dataset_name("image");
      frame_meta.set_data_type(FrameProcessor::raw_16bit);
      frame_meta.set_compression_type(FrameProcessor::no_compression);
      boost::shared_ptr<Frame> out_frame = out_frame_;
      image_ptr_ = NULL;
      out_frame->set_meta_data(frame_meta);
      out_frame->set_frame_number(image_number_);

      LOG4CXX_DEBUG_LEVEL(2, logger_, "fetching LATRD buffer for frame #" << image_number_);
      return out_frame;
    }

    void LATRDImage::mark_sent()
    {
        sent_ = true;
    }

    bool LATRDImage::get_sent()
    {
        return sent_;
    }

} /* namespace FrameProcessor */

