// Aicent Stack | RTTP (Real-Time Transport Protocol)
// Domain: RTTP.com
// Purpose: Sub-millisecond asynchronous pulse frame for Sovereign AI Nervous System
// Status: RFC-001 Draft. 
// License: Apache-2.0 or MIT.
// rttp/src/header.rs — the neural backbone of the Aicent Stack
//! RTTP Pulse Frame Header

use serde::{Serialize, Deserialize};
use std::time::{SystemTime, UNIX_EPOCH};

#[repr(C, packed)]
#[derive(Clone, Copy, Debug, Serialize, Deserialize)]
pub struct PulseFrameHeader {
    pub magic: u32,              // 0x5254_5450 ("RTTP")
    pub version: u16,            // 0x0100
    pub flags: u16,              // bit0: multicast, bit1: fec, bit2: kv_delta
    pub priority: u8,
    pub timestamp_ns: u64,
    pub task_id: u128,
    pub semantic_hash: u64,
    pub context_snapshot_id: u64,
    pub payload_len: u32,
    pub checksum: u32,
}

impl PulseFrameHeader {
    pub fn new(task_id: u128, semantic_hash: u64, payload_len: usize) -> Self {
        let now = SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .unwrap()
            .as_nanos() as u64;

        Self {
            magic: 0x5254_5450,
            version: 0x0100,
            flags: 0b0000_0111,
            priority: 128,
            timestamp_ns: now,
            task_id,
            semantic_hash,
            context_snapshot_id: 0,
            payload_len: payload_len as u32,
            checksum: 0,
        }
    }

    pub fn serialize(&self, payload: &[u8]) -> Vec<u8> {
        let mut frame = Vec::with_capacity(64 + payload.len());
        let header_bytes = unsafe {
            std::slice::from_raw_parts(self as *const _ as *const u8, 64)
        };
        frame.extend_from_slice(header_bytes);
        frame.extend_from_slice(payload);
        frame
    }
}

// Zero-copy receive example
pub fn on_pulse_received(frame: &[u8]) {
    if frame.len() < 64 {
        return;
    }
    let header = unsafe { &*(frame.as_ptr() as *const PulseFrameHeader) };
    if header.magic != 0x5254_5450 {
        return;
    }
    // TODO: later connect to rpki & zcmk
    println!("RTTP Pulse received | Task: {:x} | Semantic: {:x}", header.task_id, header.semantic_hash);
}
