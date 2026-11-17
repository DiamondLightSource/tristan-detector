/*
 * TristanExceptions.h
 *
 *  Created on: 17 Aug 2017
 *      Author: gnx91527
 */

#ifndef FRAMEPROCESSOR_INCLUDE_TRISTANEXCEPTIONS_H_
#define FRAMEPROCESSOR_INCLUDE_TRISTANEXCEPTIONS_H_
#include <exception>
#include <stdexcept>

namespace FrameProcessor
{
class TristanProcessingException: public std::runtime_error
{
public:
	TristanProcessingException(const std::string& message) :
		msg_(message),
		std::runtime_error(message)
	{

	}

	virtual ~TristanProcessingException() throw()
	{
	}

	virtual const char* what() const throw()
	{
		return msg_.c_str();
	}

private:
	std::string msg_;
};

class TristanTimestampMismatchException: public TristanProcessingException
{
public:
	TristanTimestampMismatchException(const std::string& message) :
		TristanProcessingException(message)
	{
	}

	virtual ~TristanTimestampMismatchException() throw()
	{
	}
};

}

#endif /* FRAMEPROCESSOR_INCLUDE_TRISTANEXCEPTIONS_H_ */
