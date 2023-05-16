#!/usr/bin/env python3

# This is a helpful little script which generates some pseudo-random Tristan
# count-mode events in an Image (= a frame). It puts the events into packets
# and sends them down a udp socket to a destination of your choice, and in
# a packet the pixel-coordinates are global as in the 10m.
# It also
# applies those events to a pixel-canvas and saves the frames in an h5 file
# in local (1 module) co-ordinates for you to use as reference.
#
# It is here to mimic the effect of the tristan in count mode.
# see the compare_files.py script which will compare the output of this with
# the output of the DAQ system.

import sys;
import numpy;
from scipy import stats;
import math;
import random;
import matplotlib.pyplot;
import time;
import threading;
import percival_detector.carrier.const;
from collections import OrderedDict;
import h5py;
import argparse;
import os;
import re;
import scapy.utils;
from scapy.utils import *;
from scapy.all import *;
import socket
import struct;

random.seed(100);

integral_data_word_mask       = 0xFC00000000000000;
integral_data_word_value      = 0x9000000000000000;

integral_chip_x_mask          = 0x0003FFE000000000;
integral_chip_y_mask          = 0x0000001FFF000000;
integral_i_tot_mask           = 0x0000000000FFFC00;
integral_evt_count_mask       = 0x00000000000003FF;

integral_final_packet_mask    = 0xF000FFFF00000000;
integral_final_packet_value   = 0xC00071B000000000;


serverAddressPort   = ("", 0)
bufferSize          = 1024
dwords_per_packet    = 1020; # I think the max packet is 1024 but I don't know what that includes.
module_pixels_x     = 2069; # this is column
module_pixels_y     = 515; # this is rows
module_spacing_x = module_pixels_x + 45;
module_spacing_y = module_pixels_y + 117;

# Create a UDP socket at client side

UDPClientSocket = socket.socket(family=socket.AF_INET, type=socket.SOCK_DGRAM)

class Image:

  def __init__(self, module_idx, image_idx):
    self.module_idx = module_idx;
    self.image_idx = image_idx;
    self.events = [];

  def send_packet(self, packet_idx):
    list_words = self.get_packet(packet_idx);
    payload = struct.pack("<"+"Q"*len(list_words), *list_words);
    print("sending packet to ", serverAddressPort);
    UDPClientSocket.sendto(payload, serverAddressPort)


  def send_all(self):
    print("sending ", self.get_num_packets(), " packets");
    for i in range(0, self.get_num_packets()+1):
      self.send_packet(i);
    
  def mod_offset_x(self):
    # module indexing is column-major
    mod_row = self.module_idx % 5;
    mod_col = self.module_idx // 5;
    mod_offset_x = mod_col * (module_spacing_x);

    return mod_offset_x;

  def mod_offset_y(self):
    # module indexing is column-major
    mod_row = self.module_idx % 5;
    mod_col = self.module_idx // 5;

    mod_offset_y = mod_row * (module_spacing_y);
    return mod_offset_y;

  def gen_image(self, num_words):
    self.events=[];
    for i in range (0, num_words):
      x = random.randrange(self.mod_offset_x(), self.mod_offset_x() + module_pixels_x);
      y = random.randrange(self.mod_offset_y(), self.mod_offset_y() + module_pixels_y);
      count = random.randrange(1,100);
      if i==0:
        # deliberately put 5 at (0,0) for debug purposes.
        self.events.append((self.mod_offset_x(),self.mod_offset_y(),1));
      else:
        self.events.append((x,y,count));

  def get_screen(self):
    canvas = numpy.zeros((module_pixels_x, module_pixels_y), dtype="uint16");

    for evt in self.events:
      (x,y,pix) = evt;
      x -= self.mod_offset_x();
      y -= self.mod_offset_y();
      canvas[x,y] += pix;

    return canvas;

  def save_h5(self, label):
    filename = format("module{:02d}_fr{:02d}_{}.h5".format(self.module_idx, self.image_idx, label));
    fh = h5py.File(filename, "w");

    fh.create_dataset("image", (module_pixels_y, module_pixels_x), dtype="uint16");

    fh["image"][:,:] = self.get_screen().transpose();
    fh.close();

  """ packet_index can go [0,num_packets+1] and the one at the end is the special
      final word packet. This is a bit loony and we should do something different.
  """
  def get_packet(self, packet_index):
      # ret is a list of uint64s=words.
      ret = [];
      if(packet_index < self.get_num_packets()):
        event_count = self.get_num_events_in_packet(packet_index);

        hw1 = get_header_word1(idle=0, word_count=event_count+3);
        hw2 = get_header_word2(packet_index, self.image_idx);
        # timestamp
        hw3 = 0;
        # control-word
        hw3 |= 0x8000000000000000;

        ret = [0,hw1,hw2,hw3];
        start_idx = dwords_per_packet * packet_index;
        for idx in range(start_idx, min(len(self.events), start_idx + dwords_per_packet)):
          ret.append(get_pixel_word(self.events[idx]));

        if(4+event_count != len(ret)):
          print("Assertion failure!");        


      elif(packet_index == self.get_num_packets()):
        # special end of stream packet; expected to be in a different packet
        hw1 = get_header_word1(idle=0, word_count=4);
        hw2 = get_header_word2(packet_index, self.image_idx);
        # timestamp
        hw3 = 0;
        # control-word
        hw3 |= 0x8000000000000000;

        ret = [0,hw1,hw2,hw3,integral_final_packet_value];

        
      else:
        print("Error packet index out of range");
        exit(1);

      return ret;

  def get_events_each_packet(self):
      ret = [];
      num_words = self.get_num_events();

      while 0<num_words:
        take = min(dwords_per_packet, num_words);
        num_words -= take;
        ret.append(take);

      return ret;

  def get_num_events_in_packet(self, packet_idx):
      try:
        return self.get_events_each_packet()[packet_idx];
      except:
        return 0;
      
  def get_num_packets(self):
      return len(self.get_events_each_packet());

  def get_num_events(self):
      return len(self.events);

  def print_events(self):
    for evt in self.events:
      (x,y,pix) = evt;
      print("event: {:04d}, {:04d}, {}".format(x,y,pix));
    print("num events:", self.get_num_events());

  def print_screen(self):
    img = self.get_screen();
    nzcount = 0;
    (rows,cols) = img.shape;
    for r in range(0,rows):
       for c in range(0,cols):
          if img[r,c]:
            nzcount += 1;
            print("pixel {:04d},{:04d} is {}".format(r,c,img[r,c]));
    print("non-zero pixels:", nzcount);

def get_header_word1(idle, word_count):
    ret = 0;
    ret |= 0x800;

    if(idle):
      ret |= 0x3F800;
      word_count = 0;
    else:
      ret |= (word_count & 0x7ff);

    return ret;

def get_header_word2(packet_id, image_num):
    ret = (packet_id & 0xffffffff);
    ret |= (image_num & 0xffffff) << 32;

    return ret;

def get_pixel_word(pixcnt):
    (chip_x,chip_y,count) = pixcnt;
    ret = 0;
    ret |= integral_data_word_value;
    ret |= ((chip_x << 37) & integral_chip_x_mask);
    ret |= ((chip_y << 24) & integral_chip_y_mask);
    ret |= ((count+1) << 10) & integral_i_tot_mask;
    ret |= (count << 0) & integral_evt_count_mask;


    return ret;
    

def save_h5(images, filename):
    fh = h5py.File(filename, "w");
    fh.create_dataset("image", (len(images), module_pixels_y, module_pixels_x), dtype="uint16");
    
    for idx in range(0, len(images)):
      fh["image"][idx,:,:] = images[idx].get_screen().transpose();

    fh.close();
    

def process_pcap2(file_name):
    print('Opening {} for count'.format(file_name))
    frame_num2packet_count = {};
    pcount = 0

    myreader = RawPcapReader(file_name);
    for (pkt_data, pkt_metadata,) in myreader:
        pcount +=1;

    print("packet count: ", pcount);

def is_control_word(data_word):

    ctrlWord = bool(data_word & 0x8000000000000000);
    return ctrlWord;

def check_for_integral_data_word(data_word):
    return ((data_word & integral_data_word_mask) == integral_data_word_value);

def check_for_final_packet_word(data_word):
    return ((data_word & integral_final_packet_mask) == integral_final_packet_value);

def process_data_word(data_word):
    if (check_for_integral_data_word(data_word)):
      # Extract the information from the data word
      chip_x = ((data_word&integral_chip_x_mask)>>37);
      chip_y = ((data_word&integral_chip_y_mask)>>24);
      i_tot = ((data_word&integral_i_tot_mask)>>10);
      event_count = (data_word & integral_evt_count_mask);
      return (chip_x, chip_y, i_tot, event_count);
    else:
     # print("oh dear this is not an integral data word!");
      return (None, None, None, None);


def options():
    desc = "Simulator of a Tristan in count mode, creating random events and saving to h5, and sending in packets to endpoint.";
    parser = argparse.ArgumentParser(description=desc)

    parser.add_argument("-e", "--endpoint", default="127.0.0.1:61657", help="udp endpoint to send to (127.0.0.1:61657)")

    parser.add_argument("-w", "--words", type=int, default=20, help="number of random-words to send per frame. 1 packet={} (20)".format(dwords_per_packet));
    parser.add_argument("-m", "--module", default=0, help="moduleid [0,9] (0)", type=int);
    parser.add_argument("-f", "--frames", default=1, help="number of frames to send (1)", type=int);
    parser.add_argument("-l", "--label", default="XYZ", help="label to put in h5 filename (XYZ)");
    parser.add_argument("--print_events", default=False, action="store_true", help="print events to std out (F)");
    parser.add_argument("--print_screen", default=False, action="store_true", help="print image to std out (F)");

    args = parser.parse_args()
    return args;


def main():
    global serverAddressPort;
    args = options();
    endpoint = args.endpoint.split(":");
    endpoint[1] = int(endpoint[1]);
    serverAddressPort = tuple(endpoint);
    num_words = args.words;
    module_idx = args.module;
    num_images = args.frames;

    imagelist = [];
    for image_num in range(0, num_images):
      im0 = Image(module_idx, image_num);
      im0.gen_image(num_words);
      print("module:", module_idx, " image:", image_num, "num_events:", im0.get_num_events(), " num packets:", im0.get_num_packets());
      if(args.print_events):
        im0.print_events();
      if(args.print_screen):
        im0.print_screen();
      im0.send_all();

      imagelist.append(im0);

    save_h5(imagelist, "allimages_{}.h5".format(args.label));



if __name__ == '__main__':
    main()






