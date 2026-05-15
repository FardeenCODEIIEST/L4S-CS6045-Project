#include <core.p4>
#include <v1model.p4>

#include "headers.p4"
#include "registers.p4"

parser ParserImpl(packet_in packet,
                  out headers_t hdr,
                  inout l4s_meta_t meta,
                  inout standard_metadata_t standard_metadata) {
    state start {
        packet.extract(hdr.ethernet);
        transition select(hdr.ethernet.ether_type) {
            TYPE_IPV4: parse_ipv4;
            TYPE_ARP: accept;
            default: accept;
        }
    }

    state parse_ipv4 {
        packet.extract(hdr.ipv4);
        transition accept;
    }
}

control VerifyChecksumImpl(inout headers_t hdr, inout l4s_meta_t meta) {
    apply { }
}

control IngressImpl(inout headers_t hdr,
                    inout l4s_meta_t meta,
                    inout standard_metadata_t standard_metadata) {
    bit<32> classic_protection_threshold;
    bit<32> classic_protection_budget;

    action drop() {
        mark_to_drop(standard_metadata);
    }

    action set_nhop(bit<48> dst_addr, bit<48> src_addr, bit<9> port) {
        hdr.ethernet.dst_addr = dst_addr;
        hdr.ethernet.src_addr = src_addr;
        hdr.ipv4.ttl = hdr.ipv4.ttl - 1;
        standard_metadata.egress_spec = port;
    }

    action set_egress(bit<9> port) {
        standard_metadata.egress_spec = port;
    }

    action set_mcast_grp(bit<16> mcast_grp) {
        standard_metadata.mcast_grp = mcast_grp;
    }

    table ipv4_lpm {
        key = {
            hdr.ipv4.dst_addr: lpm;
        }
        actions = {
            set_nhop;
            drop;
            NoAction;
        }
        size = 1024;
        default_action = drop();
    }

    table l2_forward {
        key = {
            hdr.ethernet.dst_addr: exact;
        }
        actions = {
            set_egress;
            set_mcast_grp;
            drop;
            NoAction;
        }
        size = 1024;
        default_action = drop();
    }

    apply {
        meta.is_l4s = 0;
        meta.queue_id = CLASSIC_QUEUE_ID;
        meta.classic_protection_triggered = 0;
        meta.current_threshold = 0;
        meta.classic_protection_budget = 0;
        meta.classic_protection_threshold = 0;
        meta.qdepth_sample = 0;
        meta.enq_qdepth_sample = 0;
        meta.delay_sample = 0;
        meta.growth_sample = 0;
        meta.threshold_exceeded = 0;

        if (hdr.ipv4.isValid()) {
            if ((hdr.ipv4.ecn == ECN_ECT1) || (hdr.ipv4.ecn == ECN_CE)) {
                meta.is_l4s = 1;
                meta.queue_id = L4S_QUEUE_ID;
            } else if ((hdr.ipv4.ecn == ECN_NOT_ECT) || (hdr.ipv4.ecn == ECN_ECT0)) {
                meta.is_l4s = 0;
                meta.queue_id = CLASSIC_QUEUE_ID;
            }

            classic_protection_threshold = 0;
            classic_protection_budget = 0;
            reg_classic_protection_threshold.read(classic_protection_threshold, REG_INDEX);
            reg_classic_protection_budget.read(classic_protection_budget, REG_INDEX);

            meta.classic_protection_threshold = classic_protection_threshold;

            /*
             * Anti-starvation guard:
             * ingress cannot directly read the live Classic queue occupancy.
             * Native Classic arrivals therefore build a small protection budget;
             * later L4S arrivals consume that budget by entering the Classic
             * queue instead of refilling the higher-priority queue.
             */
            if (classic_protection_threshold > 0) {
                if (meta.is_l4s == 0) {
                    if (classic_protection_budget < classic_protection_threshold) {
                        classic_protection_budget = classic_protection_budget + 1;
                        reg_classic_protection_budget.write(REG_INDEX, classic_protection_budget);
                    }
                } else if (classic_protection_budget > 0) {
                    classic_protection_budget = classic_protection_budget - 1;
                    reg_classic_protection_budget.write(REG_INDEX, classic_protection_budget);
                    meta.queue_id = CLASSIC_QUEUE_ID;
                    meta.classic_protection_triggered = 1;
                }
            } else if (classic_protection_budget > 0) {
                classic_protection_budget = 0;
                reg_classic_protection_budget.write(REG_INDEX, classic_protection_budget);
            }

            meta.classic_protection_budget = classic_protection_budget;
            standard_metadata.priority = meta.queue_id;
            if (hdr.ipv4.ttl <= 1) {
                drop();
            } else {
                ipv4_lpm.apply();
            }
        } else {
            standard_metadata.priority = CLASSIC_QUEUE_ID;
            l2_forward.apply();
        }
    }
}

control EgressImpl(inout headers_t hdr,
                   inout l4s_meta_t meta,
                   inout standard_metadata_t standard_metadata) {
    bit<32> current_qdepth;
    bit<32> current_enq_qdepth;
    bit<32> current_delay;
    bit<32> threshold;
    bit<32> previous_enq_qdepth;
    bit<32> growth;

    apply {
        if (hdr.ipv4.isValid()) {
            current_qdepth = (bit<32>)standard_metadata.deq_qdepth;
            current_enq_qdepth = (bit<32>)standard_metadata.enq_qdepth;
            current_delay = (bit<32>)standard_metadata.deq_timedelta;
            
            threshold = 0;
            previous_enq_qdepth = 0;
            growth = 0;

            if (meta.queue_id == L4S_QUEUE_ID) {
                reg_l4s_threshold.read(threshold, REG_INDEX);
                reg_l4s_prev_enq_qdepth.read(previous_enq_qdepth, REG_INDEX);
            } else {
                reg_classic_threshold.read(threshold, REG_INDEX);
                reg_classic_prev_enq_qdepth.read(previous_enq_qdepth, REG_INDEX);
            }

            if (current_enq_qdepth >= previous_enq_qdepth) {
                growth = current_enq_qdepth - previous_enq_qdepth;
            } else {
                growth = 0;
            }

            meta.current_threshold = threshold;
            meta.qdepth_sample = current_qdepth;
            meta.enq_qdepth_sample = current_enq_qdepth;
            meta.delay_sample = current_delay;
            meta.growth_sample = growth;

            if ((threshold > 0) &&
                (current_qdepth >= threshold) &&
                (hdr.ipv4.ecn != ECN_NOT_ECT)) {
                meta.threshold_exceeded = 1;
                hdr.ipv4.ecn = ECN_CE;
            }

            if (meta.queue_id == L4S_QUEUE_ID) {
                reg_l4s_qdepth.write(REG_INDEX, current_qdepth);
                reg_l4s_delay.write(REG_INDEX, current_delay);
                reg_l4s_growth.write(REG_INDEX, growth);
                reg_l4s_prev_enq_qdepth.write(REG_INDEX, current_enq_qdepth);
            } else {
                reg_classic_qdepth.write(REG_INDEX, current_qdepth);
                reg_classic_delay.write(REG_INDEX, current_delay);
                reg_classic_growth.write(REG_INDEX, growth);
                reg_classic_prev_enq_qdepth.write(REG_INDEX, current_enq_qdepth);
            }
        }
    }
}

control ComputeChecksumImpl(inout headers_t hdr, inout l4s_meta_t meta) {
    apply {
        update_checksum(
            hdr.ipv4.isValid(),
            {
                hdr.ipv4.version,
                hdr.ipv4.ihl,
                hdr.ipv4.diffserv,
                hdr.ipv4.ecn,
                hdr.ipv4.total_len,
                hdr.ipv4.identification,
                hdr.ipv4.flags,
                hdr.ipv4.frag_offset,
                hdr.ipv4.ttl,
                hdr.ipv4.protocol,
                hdr.ipv4.src_addr,
                hdr.ipv4.dst_addr
            },
            hdr.ipv4.hdr_checksum,
            HashAlgorithm.csum16
        );
    }
}

control DeparserImpl(packet_out packet, in headers_t hdr) {
    apply {
        packet.emit(hdr.ethernet);
        packet.emit(hdr.ipv4);
    }
}

V1Switch(
    ParserImpl(),
    VerifyChecksumImpl(),
    IngressImpl(),
    EgressImpl(),
    ComputeChecksumImpl(),
    DeparserImpl()
) main;
