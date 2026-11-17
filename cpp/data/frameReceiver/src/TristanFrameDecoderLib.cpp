/*
 * TristanFrameDecoderLib.cpp
 *
 *  Created on: 8 Mar 2017
 *      Author: gnx91527
 */


#include "TristanFrameDecoder.h"
#include "ClassLoader.h"

namespace FrameReceiver
{
    /**
     * Registration of this decoder through the ClassLoader.  This macro
     * registers the class without needing to worry about name mangling
     */
    REGISTER(FrameDecoder, TristanFrameDecoder, "TristanFrameDecoder");

} // namespace FrameReceiver



