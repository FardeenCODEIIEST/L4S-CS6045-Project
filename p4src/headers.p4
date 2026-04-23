#ifndef L4S_HEADERS_P4
#define L4S_HEADERS_P4

#include <core.p4>

const bit<16> TYPE_IPV4 = 0x0800;

const bit<2> ECN_NOT_ECT = 0b00;
const bit<2> ECN_ECT1    = 0b01;
const bit<2> ECN_ECT0    = 0b10;
const bit<2> ECN_CE      = 0b11;

const bit<3> CLASSIC_QUEUE_ID = 0;
const bit<3> L4S_QUEUE_ID     = 1;

header ethernet_t {
    bit<48> dst_addr;
    bit<48> src_addr;
    bit<16> ether_type;
}

header ipv4_t {
    bit<4>  version;
    bit<4>  ihl;
    bit<6>  diffserv;
    bit<2>  ecn;
    bit<16> total_len;
    bit<16> identification;
    bit<3>  flags;
    bit<13> frag_offset;
    bit<8>  ttl;
    bit<8>  protocol;
    bit<16> hdr_checksum;
    bit<32> src_addr;
    bit<32> dst_addr;
}

struct headers_t {
    ethernet_t ethernet;
    ipv4_t     ipv4;
}

struct l4s_meta_t {
    bit<1>  is_l4s;
    bit<3>  queue_id;
    bit<32> current_threshold;
    bit<32> qdepth_sample;
    bit<32> enq_qdepth_sample;
    bit<32> delay_sample;
    bit<32> growth_sample;
    bit<1>  threshold_exceeded;
}

#endif
