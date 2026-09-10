# DespairPlay GUI

GTK4 / libadwaita app that inspects the Linux **AirPlay sender** stack (Avahi, PipeWire RAOP, firewall/mDNS) and shows which parts of this confusing house of cards are installed and active.

Linux can send audio to AirPlay speakers via **RAOP (AirPlay 1)** but it's a confusing mess. This app diagnoses potential issues instead of just shrugging and recommending “install more packages”. I spaffed this project out after sliding into despair tryng to understand why my soundbar stopped playing music one day. 

It does **not** implement an AirPlay receiver, screen mirroring, or AirPlay 2 sending.

## Install on Ubuntu or Zorin

CI builds a `.deb` on GitHub Actions (repo: [byintention/despairplay-gui](https://github.com/byintention/despairplay-gui)). Download `despairplay_*_all.deb` from the workflow artifact, then:

```bash
sudo apt install ./despairplay_0.1.0-1_all.deb
```

GTK/libadwaita come in as package dependencies. Remove with `sudo apt remove despairplay`.

To run from a git checkout on this machine: `make install-dev` then `make run` (venv must be `--system-site-packages` so distro `gi` is visible).

## Requirements

A computer running Ubuntu Linux with Gnome desktop. Maybe Debian, Zorin, Elementary etc will work. KDE probably won't. 

Beyond that I honestly have no idea. I somehow got Airplay installed and working months ago by installing various packages. 

The app needs GTK packages, but I think they were installed already. 

Having an Airplay speaker probably helps. 

Built and tested on Ubuntu 24/Gnome with Cursor doing the heavy lifting. 

**Note:** I also have 'Gnome Airplay Toggle' installed which complicates things. 'Gnome tweaks' seems pretty flaky and interfered with that.

## So, how does 'Airplay' work on Linux?

This overview covers the arcane steps required to start sending audio to Airplay speakers from Linux (in my case Ubuntu 24/Gnome and ZorinOS). It does not cover screen mirroring, or making your Linux computer into an Airplay receiver.

Airplay can 'hijack' a speaker that is already playing sound from another source, so that can confuse matters. My soundbar is connected to my TV. If I'm playing music from a computer and the TV turns on, it will take the audio over.

### Finding Airplay Speakers

On a Mac, Airplay depends on **Bonjour** which is Apple's name for **mDNS** (**multicast DNS**), a 'zero config' networking discovery service. That's a way to easily find things on your network and enables names like `shinymac.local` instead of having to type `192.168.1.154` or whatever that is easy to forget. Devices like Airplay speakers broadcast themselves on the local network.

Macs just deal with this behind the scenes, but like many things on Linux we have to set it up manually after spending (too many) hours reading all about it. Linux has to recreate the Bonjour system with mDNS and **Avahi**. Linux mDNS is handled by Avahi as a *daemon*, so that needs installing if it's not already there.

Also you might need to open a port on your firewall so it can see the devices broadcasting on your network. Not doing this had me confused for a while.

### Sending Audio to Airplay Speakers

Once we've found the Airplay speakers, we need to send something to them.

**PulseAudio** was the old way of doing audio on Linux. Most systems now use **Pipewire**, which can also pretend to be PulseAudio for compatibility. Linux audio can also involve ALSA and JACK. OK? OK. PipeWire handles audio natively now while supplying compatibility layers (`pipewire-pulse`) so old PulseAudio commands still work seamlessly.

Airplay is Apple's newer name for their **RAOP** **(Remote Audio Output Protocol)** format. It is the underlying networking protocol Apple created back in 2004 for **AirTunes** (which was later rebranded to **AirPlay**). 

RAOP is based on the **RTSP (Real-Time Streaming Protocol)** to establish connections and controls, and then streams audio over UDP using **Apple Lossless Audio Codec (ALAC)**. It's encrypted but the RSA public key stored in iTunes was extracted by [Jon Lech Johansen](https://en.wikipedia.org/wiki/Jon_Lech_Johansen), enabling third-party software to stream music to Airplay devices.

While you *can* load modules using PulseAudio compatibility utilities like `pactl load-module module-raop-discover`, modern PipeWire setups typically handle RAOP discovery via PipeWire's native configuration files (specifically loading `libpipewire-module-raop-discover` via `pipewire.conf.d` or installing a zeroconf/extras package like `pipewire-zeroconf`).

Told you it was a mess.

### System Tray Airplay Toggle

There's also a script to add an Airplay speaker toggle to the system tray

[https://github.com/craw0967/pipewire-airplay-toggle](https://github.com/craw0967/pipewire-airplay-toggle)



## References

[https://en.wikipedia.org/wiki/AirPlay](https://en.wikipedia.org/wiki/AirPlay)

[https://en.wikipedia.org/wiki/Remote_Audio_Output_Protocol](https://en.wikipedia.org/wiki/Remote_Audio_Output_Protocol#)