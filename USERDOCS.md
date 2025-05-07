# User Documentation of the TwinRF69

Make sure that you install RPi.GPIO and spidev with:

    sudo apt install python3-rpi.gpio python3-spidev

Then open:

    raspi-config

Ensure you enable SPI. Then save and reboot.

Also, you will need to ensure that you swap the names of NODE and OTHER node in one of the two TwinRF69_test.py files.

Now, we have made the decision to build  basned on a TUN or IP based interface and to utlise 6LoWPAN and an IPv6 stack.

Let's setup an interface:

    sudo ip tuntap add dev tun0 mode tun
    sudo ip link set dev tun0 up
    sudo ip addr add 2001:db8::1/64 dev tun0
    sudo sysctl -w net.ipv6.conf.all.forwarding=1


Obviously you will need to change the userspace portion of the IPv6 interface for each  network adapter.


