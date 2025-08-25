# Design and Decisions

This document describes the fundamental design decisions of the TwinRF69.

The goal of the project is  to pursue a radio technology that provided greater range than the regular Pi 2.4GHz WiFi chips, but equally to support higher transimission rates than those found in LoRa transmitters. Ideally, a goal of re-using a technology that could also be built for less than $10 USD was important.

At the moment, the best current plan is to use a  dual RF chip design, using the RFM69 chip, which can be bought in 433, and 868/915 MHz variants. 

At present the technology works and it is possible to successfully send and recieve on both chips.

The next step is to see if it is possible to make this technology talk IP. One eof the considerations is to see if it is possible to make it talk 6LowPAN.

The plan is that we will use the lower band, the 433 MHz band for route discovery and for acknowledgements. The higher frequency, the 868/915MHz band will be used for the transmission of data frames.
