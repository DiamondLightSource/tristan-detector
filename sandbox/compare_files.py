#!/usr/bin/env python3

# this script will open two h5 files, read the dataset "image" in both, and compare them.
# This is useful because the tristan count-mode simulator creates one such file, and the
# DAQ produces another.
# It can also just dump the non-zero pixel data to std::out for you to look at.


import subprocess;
import sys;
import numpy;
import math;
import random;
import time;
import logging;
import h5py;

import argparse;
import os;
import re;

#sys.path.append("/dls/science/users/ulw43618/Projects2/gitlab/tristan-detector/control/")

log_levels = {
    'error': logging.ERROR,
    'warning': logging.WARNING,
    'info': logging.INFO,
    'debug': logging.DEBUG,
}

def print_as_text(filen):
  if(os.path.isfile(filen)):
    print("opening ", filen);

    fh = h5py.File(filen, "r");
    img = numpy.asarray(fh["image"]);

    if len(img.shape)==2:
      (rr,cc) = img.shape;
      for r in range(0,rr):
        for c in range(0,cc):
          if img[r,c]:
            print(r,c, " is " , img[r,c]);
    else:
      (ff,rr,cc) = img.shape;

      for f in range(0,ff):
        for r in range(0,rr):
          for c in range(0,cc):
            if img[f,r,c]:
              print(f,r,c, " is " , img[f,r,c]);

    fh.close();

def compare_files(filen1, filen2):
  print("opening ", filen1);

  fh1 = h5py.File(filen1, "r");
  img1 = numpy.asarray(fh1["image"]);

  print("opening ", filen2);

  fh2 = h5py.File(filen2, "r");
  img2 = numpy.asarray(fh2["image"]);

  if(img1.shape == img2.shape):
    print("shape is ", img1.shape);
    (ff,rr,cc) = img1.shape;

    anydiffer = False;
    for f in range(0,ff):
      differ = False;
      for r in range(0,rr):
        for c in range(0,cc):
          if img1[f,r,c] != img2[f,r,c]:
            print(f,r,c, " is " , img1[f,r,c], " vs ", img2[f,r,c]);
            differ = True;
            anydiffer = True;
      if differ == False:
        print("Frame ", f, " is the same");

    if anydiffer:
      print("Files differ");
    else:
      print("Files are equivalent");

  else:
    print("File shapes differ");

  

def main():
  parser = argparse.ArgumentParser(
      prog='thisprog', description='LATRD pixel counter'
  )



  parser.add_argument(
      '-f1', '--file1', type=str, dest='file1',
      default="",
      help='h5file #1 name to open and compare'
  )

  parser.add_argument(
      '-f2', '--file2', type=str, dest='file2',
      default="",
      help='h5file #2 name to open and compare'
  )

  parser.add_argument(
      '-d', '--dump', type=str, dest='dump',
      default="",
      help='h5file name to open, read, and print to stdout'
  )

  args = parser.parse_args();
  if os.path.exists(args.dump):
    print_as_text(args.file);
  elif(os.path.exists(args.file1) and os.path.exists(args.file2)):
    compare_files(args.file1, args.file2);
  else:
    print("could not find file(s)");



  return 0;



if __name__ == '__main__':
    main()

