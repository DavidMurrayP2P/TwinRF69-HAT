# Design and Decisions

This document describes the fundamental design decisions of the TwinRF69.

The goal of the project is to pursue a radio technology that provides greater range than regular Pi 2.4GHz WiFi chips, but equally to support higher transimission rates than those found in LoRa transmitters. Re-using a technology that could also be built for less than $10 USD was important.

At the moment, the best current plan is to use adual RF chip design, using the RFM69 chip, which can be bought in 433, and 868/915 MHz variants. At present the technology works and it is possible to successfully send and recieve on both chips.

The next step is to see if it is possible to make this technology talk IP. One of the considerations is to see if it is possible to make it talk IP by linking it to a tun interface on linux.

There are a few possible approaches for how we use the dual band radios to create one low bandwith IP link:
 * Initally it was planned to use the lower band, the 433 MHz band for route discovery and for acknowledgements. The higher frequency, the 868/915MHz band would used for the transmission of data frames. While there is something nice about this approach there is an alterative.
 * An alternat is to say that this link will always be too low bandwidth to be multi hop in any way, at least for IP data. In this case we could just simplify and say that all links were point to point and to negotiate an up and down band. So in this case, ona singel node, one radio is always listening and the other is always in sending mode.

