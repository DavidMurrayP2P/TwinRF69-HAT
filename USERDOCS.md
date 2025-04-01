# User Documentation of the TwinRF69

Make sure that you install RPi.GPIO and spidev with:

    sudo apt install python3-rpi.gpio python3-spidev

Then open:

    raspi-config

Ensure you enable SPI. Then save and reboot.

Also, you will need to ensure that you swap the names of NODE and OTHER node in one of the two TwinRF69_test.py files.

