# TwinRF69: A new wireless inteface option for the Raspberry Pi (Work in Progress)

The Twin RF69 project aims to extend the wireless capabilities of the Raspberry Pi ecosystem into two different frequencies in the sub 1GHz band. The goal of this is to provide a wireless mesh based alternative to WiFi that utilises longer range, lower power but can still talk IP. I've decided to go down the path of creating dedicated hardware after exploring all the viable options. You can read through and look at my dive into the [wireless_interface_options](WIRELESS_INTERFACE_RESEARCH.md) for the Raspberry Pi.

The current state of this project is that the hardware design and the code in this repository works. We can successfully send packets on the 915MHz and 433MHz band, and the range exceeds that of WiFi. The interfaces do not yet support IP however.

![Alt text](IMG/TwinRF69.png?raw=true "Title") <p style="text-align:center; font-style:italic;">A prototype of the TwinRF69</p>

You can find the user docs, showing you how to get started with the TwinRF69, and the design decisions around the board here:
* [USERDOCS](USERDOCS.md) 
* [DESIGN_AND_DECISIONS](DESIGN_AND_DECISIONS.md)

![Alt text](IMG/TwinRF69_with_PPZ.png?raw=true "Title") <p style="text-align:center; font-style:italic;">This project works well with the  [Soldering a header on a Raspberry Pi Zero 2](https://youtu.be/pwCCnsn2Mug) video. Photon Power Zero, pictured underneath. 

The they operate as stackable hearders for the Raspberry Pi. This si designed aronud relative low power and potentially solar, battery operation and integration with the  [Photon Power Zero](https://youtu.be/pwCCnsn2Mug) video..</p>

As an open-source project, you can find the code for the Twin RF69, the Kicad PCB files and the FDM 3D printing files below
* [Code](Code)
* [PCBs](PCBs)
* [FDM (3D Print Files)](FDM)

You can find some mounts for Raspberry Pi that include spots for SMA pigtails and power supplies in [FDM (3D Print Files)](FDM)

![Alt text](IMG/TwinRF69_full.png?raw=true "Title") <p style="text-align:center; font-style:italic;">A prototype of the TwinRF69</p>