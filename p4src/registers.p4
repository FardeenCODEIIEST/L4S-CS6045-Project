#ifndef L4S_REGISTERS_P4
#define L4S_REGISTERS_P4

const bit<32> REG_INDEX = 0;

register<bit<32>>(1) reg_l4s_threshold;
register<bit<32>>(1) reg_classic_threshold;

register<bit<32>>(1) reg_l4s_qdepth;
register<bit<32>>(1) reg_classic_qdepth;

register<bit<32>>(1) reg_l4s_delay;
register<bit<32>>(1) reg_classic_delay;

register<bit<32>>(1) reg_l4s_growth;
register<bit<32>>(1) reg_classic_growth;

/*
 * Helper state for estimating queue growth from enqueue depth. These are
 * internal dataplane-only registers; the controller can ignore them.
 */
register<bit<32>>(1) reg_l4s_prev_enq_qdepth;
register<bit<32>>(1) reg_classic_prev_enq_qdepth;

#endif
