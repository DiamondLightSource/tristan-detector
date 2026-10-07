# Project name
project(tristan-detector)

# Set C++ standard
set(CMAKE_CXX_STANDARD 11 CACHE STRING "The C++ standard to use")
set(CMAKE_CXX_STANDARD_REQUIRED ON)

# Require CMake version >=2.8
cmake_minimum_required(VERSION 2.8)

option(BUILD_SHARED_LIBS "Build shared library" ON)

# Set output directory
set(CMAKE_RUNTIME_OUTPUT_DIRECTORY ${CMAKE_BINARY_DIR}/bin)
set(CMAKE_LIBRARY_OUTPUT_DIRECTORY ${CMAKE_BINARY_DIR}/lib)

# Appends the cmake/modules path inside the MAKE_MODULE_PATH variable which stores the
# directories of additional CMake modules:
set(CMAKE_MODULE_PATH ${CMAKE_CURRENT_SOURCE_DIR}/cmake ${CMAKE_MODULE_PATH})

# Find external packages
find_package(Boost 1.41.0 REQUIRED COMPONENTS program_options system thread)
find_package(TBB REQUIRED)
find_package(HDF5 REQUIRED COMPONENTS C HL)

message(STATUS "  Boost include dirs: ${Boost_INCLUDE_DIRS}")
message(STATUS "  Boost libs:         ${Boost_LIBRARIES}")
message(STATUS "  TBB include dirs:   ${TBB_INCLUDE_DIRS}")
message(STATUS "  TBB libs:           ${TBB_LIBRARIES}")
message(STATUS "  HDF5 include dirs:  ${HDF5_INCLUDE_DIRS}")
message(STATUS "  HDF5 libs:          ${HDF5_LIBRARIES}")

# Add include directory to include path
include_directories(Include)

# Add the source subdirectory
add_subdirectory(src)
