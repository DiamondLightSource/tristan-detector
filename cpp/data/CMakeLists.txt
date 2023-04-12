set(FRAMERECEIVER_DIR ${DATA_DIR}/frameReceiver)
set(FRAMEPROCESSOR_DIR ${DATA_DIR}/frameProcessor)

# Add common/include directory to include path
include_directories(${DATA_DIR}/common/include)

add_subdirectory(${FRAMERECEIVER_DIR})
add_subdirectory(${FRAMEPROCESSOR_DIR})
add_subdirectory(test)
add_subdirectory(config)
