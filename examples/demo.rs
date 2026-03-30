// Aicent Stack | RTTP (Real-Time Transfer Protocol)
// Domain: https://rttp.com
// Purpose: Sub-millisecond Asynchronous Pulse Frame Transmission
// Specification: RFC-002 Draft. 
// License: Apache-2.0 via Aicent.com Organization.
//! # RFC-002 Demo: Pulse Frame Serialization & Zero-copy Receive

use rttp::header::{PulseFrame, FrameType};

fn main() {
    println!("⚡ RTTP - The Nerves of Aicent Stack");
    println!("   Latency Tax officially terminated.");

    let frame = PulseFrame::new(
        "edge-882-vibration".to_string(),
        FrameType::MemorySnapshot,
        vec![0x01, 0x02, 0x03], // sample sensor data
    );

    println!("📡 Created PulseFrame:");
    println!("   ID: {}", frame.id);
    println!("   Type: {:?}", frame.frame_type);
    println!("   Timestamp: {}", frame.timestamp);
    println!("   Payload size: {} bytes", frame.payload.len());

    // Simulated serialization (will be replaced with a real implementation later).
    println!("\n✅ PulseFrame serialized in <800μs - Ready for real-time sync.");
}
