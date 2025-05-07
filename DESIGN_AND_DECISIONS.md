# Design and Decisions

This document describes the fundamental design decisions of the TwinRF69.

So the goal was to pursue a radio technology that provided greater range than the 2.4GHz Wifi chips avaliable but also better data rates than LoRa transmitters. We also wanted something that could be built for less than $10 USD. 

I've settled on a dual RF chip design using the RFM69 chip which can be bought in 433 and 915 MHz variants. 

At present the technology works and it is possible to successfully send and recieve on both chips.

The next step is to see if it is possible to make this technology talk IP. One eof the considerations is to see if it is possible to make it talk 6LowPAN.
