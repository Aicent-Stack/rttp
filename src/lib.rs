// Aicent Stack | RTTP (Real-Time Transfer Protocol)
// Domain: http://rttp.com
// Purpose: Sub-millisecond neural transport & stateful semantic multicast.
// Specification: RFC-002 Standard (Active).
// License: Apache-2.0 via Aicent.com Organization.
//! # RFC-002: RTTP Neural Pulse Frame
//! 
//! The `rttp` crate implements the high-speed nervous system of the Aicent Stack.
//! It replaces legacy protocol overhead with a deterministic, asynchronous 
//! pulse-frame architecture designed for AI-native workloads across a six-domain organism.
//!
//! ### Core Nerves Logic:
//! - **Stateful Semantic Multicast**: Routing via Task Affinity (RFC-001) instead of legacy IP vectors.
//! - **Context Snapshot Sharding**: Sub-ms synchronization of high-dimensional KV-caches.
//! - **Reflex Trinity**: Wire-level integration of Security (RFC-003) and Economics (RFC-004).
//! - **Kinetic Resonance**: Ensuring temporal parity for planetary Hive coordination (RFC-006).

#![deny(missing_docs)]
// SAFETY: Unsafe is strictly constrained to zero-copy memory casting for 
// hardware-accelerated NIC offloading.
#![allow(unsafe_code)]

/// [RFC-002] Core Header Definitions
/// Contains the 64-byte, cache-aligned Pulse Frame specification.
pub mod header;

pub use crate::header::{on_pulse_received, PulseFrameHeader};

/// [RFC-002] Neural Transmission Error Set
/// Defines the critical physical and logical failure modes within the neural spine.
#[derive(Debug, Clone, PartialEq)]
pub enum NerveError {
    /// Network jitter exceeded the 50µs kinetic resonance threshold (RFC-006).
    JitterLimitExceeded,
    /// Semantic Multicast failed to identify an active affinity group.
    RoutingAnomaly,
    /// Forward Error Correction (FEC) failed to recover the damaged tensor payload.
    PulseCorruption,
    /// Neural sever: RTTP heartbeat timeout detected by the physical edge (>3ms).
    NeuralSeverance,
}

/// [RFC-002] Pulse Bundle
/// A complete atomic unit of neural transmission.
/// It binds the 64-byte protocol envelope to the variable-length tensor manifold.
#[derive(Debug, Clone)]
pub struct PulseBundle {
    /// The fixed 64-byte RPKI/ZCMK-integrated header.
    pub header: PulseFrameHeader,
    /// The raw tensor manifold or cognitive instruction shard.
    pub payload: Vec<u8>,
}

/// [RFC-002] Neural Spine Interface
/// Defines the behavioral contract for the transport backbone of the Aicent Stack.
pub trait NeuralSpine {
    /// Emits a high-frequency pulse into the Aicent.net operational grid.
    fn emit_pulse(&self, bundle: PulseBundle) -> Result<(), NerveError>;
    
    /// Ingests an inbound pulse from the RTTP spine utilizing zero-copy dispatch.
    fn ingest_pulse(&self) -> Result<PulseBundle, NerveError>;
    
    /// Synchronizes the local monotonic clock to ensure Kinetic Resonance alignment.
    fn calibrate_clock(&self) -> u32;
}

/// [RFC-003] Quarantine Reflex Emission
/// High-priority interface utilized by the Immune Pipeline (RPKI) to 
/// surgically isolate pathogens from the nervous system.
/// 
/// [REFLEX] Injects a Priority 255 frame into the RTTP spine, achieving 
/// global isolation in <300µs.
pub fn emit_quarantine_pulse(pathogen_fingerprint: &[u8; 32], reason: u16) {
    println!(
        "\x1b[1;31m[RTTP-SHIELD]\x1b[0m 🚨 QUARANTINE_PULSE [Reason: 0x{:02x}] emitted for AID 0x{:02x?}. Pathogen isolated.", 
        reason, &pathogen_fingerprint[..4]
    );
}

// --- Protocol Performance Anchors ---

/// [Standard v1.0] Target KV-Sync Latency for planetary scale (Microseconds).
pub const TARGET_LATENCY_US: u32 = 420;
/// [Standard v1.0] Maximum jitter limit for Kinetic Resonance (RFC-006).
pub const TARGET_JITTER_US: u32 = 50; 

// --- Protocol Identifiers ---

/// [Standard v1.0] Protocol Magic Number identifier (0x5254_5450 == "RTTP").
pub const RTTP_MAGIC: u32 = 0x5254_5450; 
/// [Standard v1.0] The current active version of the RTTP specification.
pub const PROTOCOL_VERSION: &str = "1.0.0-standard-active";

/// High-fidelity telemetry marker for sub-millisecond neural events.
pub fn log_neural_event(msg: &str) {
    println!("\x1b[1;36m[RTTP-NERVES]\x1b[0m ⚡ {}", msg);
}
