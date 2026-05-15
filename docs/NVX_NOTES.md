# NVX Mock Notes

The nvx_http device type is a basic REST style mock. It is not a real Crestron NVX endpoint.

## Useful for

- HTTP reachability
- route and status polling
- stream location state
- online and offline scenarios
- no video sync scenarios
- delayed or failed replies

## Not covered

- real NVX firmware behavior
- Crestron native device extenders
- multicast video transport
- HDMI signal behavior
- USB routing
- network timing behavior

## Current mock behavior

GET, POST, and PUT requests return JSON with the device id, role, stream location, video sync state, and requested path.

POST and PUT bodies can include streamLocation or stream_location. The simulator stores the value in memory.

## Next step

Capture the exact NVX API paths your Crestron program uses. Then add path specific mock replies instead of relying only on the generic response.
