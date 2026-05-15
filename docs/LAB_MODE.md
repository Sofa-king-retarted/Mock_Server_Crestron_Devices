# Lab Mode Notes

Use this simulator as a fake device layer for Crestron testing.

## Recommended Crestron structure

Add a global Lab Mode setting in your program.

- Real Mode points modules at real IP addresses.
- Lab Mode points modules at the simulator PC IP and configured ports.

## What this validates

- TCP/UDP/HTTP connectivity
- command formatting
- response parsing
- online/offline handling
- timeout/retry behavior
- UI feedback behavior
- route-state logic
- startup/recovery logic

## What still needs real hardware

- HDMI sync
- HDCP
- EDID
- NVX multicast video
- USB routing
- audio paths
- AVB/gPTP/MSRP
- touchpanel firmware behavior
- Crestron native device extender behavior

## IP layout options

### Option 1: one lab PC IP, different ports

This is easiest. Every fake device runs on the same PC IP, but each device uses a unique port.

### Option 2: multiple IP aliases

Use this when your Crestron program needs multiple devices using the same vendor port. Add extra IPs to the Windows NIC and bind simulator instances to those addresses.

### Option 3: VM/container per device

Useful later, but more work on Windows networking.
