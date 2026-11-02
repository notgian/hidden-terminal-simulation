#!/usr/bin/env python3
"""
Hidden-terminal simulation for IEEE 802.11 using the ns-3 Python bindings.

Topology: one AP and N stations. Every station can hear the AP, but no station
can hear any other station (explicit matrix loss model), so all stations are
mutually hidden. All stations send saturated/periodic UDP uplink traffic to the AP.

Methods:
  csma      baseline CSMA/CA, RTS/CTS disabled
  rts-cts   static RTS/CTS, used for every frame
  adaptive  RTS/CTS switched on/off at run time from the measured failure
            ratio and the frame airtime (a FIRST-DRAFT definition; edit it
            to match your final adaptive scheme)
"""

import argparse
import csv
import itertools
import math
import random
import statistics
import sys
import time
from pathlib import Path

from ns import ns

METHODS = ["csma", "rts-cts", "adaptive"]
OFDM_RATES = [6, 9, 12, 18, 24, 36, 48, 54]
SIFS_US = 16
APP_START = 1.0  # seconds; leaves time for association
UDP_PORT = 9
MIN_PAYLOAD = 12  # UdpClient's SeqTsHeader is 12 bytes
MAX_PAYLOAD = 1472  # largest UDP payload without IP fragmentation
RTS_OFF = 65535  # threshold larger than any frame -> RTS/CTS never used
RTS_ON = 0  # threshold 0 -> RTS/CTS always used

CSV_FIELDS = [
    "method",
    "nodes",
    "payload_bytes",
    "offered_load_mbps",
    "phy_rate_mbps",
    "sim_time_s",
    "warmup_s",
    "run",
    "seed",
    "throughput_mbps",
    "collision_rate",
    "mean_delay_ms",
    "p95_delay_ms",
    "rx_packets",
    "data_failures",
    "rts_failures",
    "rts_on_fraction",
]

# --------------------------------------------------------------------------
# C++ helpers compiled by cppyy at start-up. They cover the parts that are
# awkward through the Python bindings: the per-pair loss matrix, trace sinks,
# and the run-time adaptive controller.
# --------------------------------------------------------------------------
CPP_HELPERS = r"""
#include <algorithm>
#include <vector>
using namespace ns3;

namespace htsim {

static double g_warmup = 0.0;
static uint64_t g_rxPackets = 0, g_rxBytes = 0, g_dataFailed = 0, g_rtsFailed = 0;
static double g_delaySum = 0.0;
static std::vector<double> g_delays;

// adaptive controller state
static uint64_t g_adaptFail = 0, g_adaptSucc = 0, g_lastFail = 0, g_lastSucc = 0;
static bool g_rtsOn = false, g_pHatInit = false;
static double g_pHat = 0.0, g_window = 0.5, g_alpha = 0.3, g_margin = 1.0;
static double g_dataAirUs = 0.0, g_ovhUs = 0.0, g_stop = 0.0, g_onTime = 0.0;
static uint32_t g_minSamples = 20;

void Reset() {
  g_rxPackets = g_rxBytes = g_dataFailed = g_rtsFailed = 0;
  g_delaySum = 0.0; g_delays.clear();
  g_adaptFail = g_adaptSucc = g_lastFail = g_lastSucc = 0;
  g_rtsOn = false; g_pHatInit = false; g_pHat = 0.0; g_onTime = 0.0;
}

void SetWarmup(double w) { g_warmup = w; }
static bool Measuring() { return Simulator::Now().GetSeconds() >= g_warmup; }

Ptr<YansWifiChannel> MakeChannel(NodeContainer nodes, double apLossDb, double otherLossDb) {
  Ptr<YansWifiChannel> channel = CreateObject<YansWifiChannel>();
  channel->SetPropagationDelayModel(CreateObject<ConstantSpeedPropagationDelayModel>());
  Ptr<MatrixPropagationLossModel> loss = CreateObject<MatrixPropagationLossModel>();
  loss->SetDefaultLoss(otherLossDb);                 // station <-> station: inaudible
  Ptr<MobilityModel> ap = nodes.Get(0)->GetObject<MobilityModel>();
  for (uint32_t i = 1; i < nodes.GetN(); ++i) {
    loss->SetLoss(ap, nodes.Get(i)->GetObject<MobilityModel>(), apLossDb, true);
  }
  channel->SetPropagationLossModel(loss);
  return channel;
}

void OnDataFailed(Mac48Address) { g_adaptFail++; if (Measuring()) g_dataFailed++; }
void OnRtsFailed(Mac48Address)  { g_adaptFail++; if (Measuring()) g_rtsFailed++; }
void OnRx(Ptr<const Packet> p) {
  g_adaptSucc++;
  if (!Measuring()) return;
  g_rxPackets++;
  g_rxBytes += p->GetSize();
  Ptr<Packet> copy = p->Copy();
  SeqTsHeader h;
  copy->RemoveHeader(h);
  double d = (Simulator::Now() - h.GetTs()).GetSeconds();
  g_delaySum += d;
  g_delays.push_back(d);
}

void ConnectTraces() {
  Config::ConnectWithoutContext(
    "/NodeList/*/DeviceList/*/$ns3::WifiNetDevice/RemoteStationManager/MacTxDataFailed",
    MakeCallback(&OnDataFailed));
  Config::ConnectWithoutContext(
    "/NodeList/*/DeviceList/*/$ns3::WifiNetDevice/RemoteStationManager/MacTxRtsFailed",
    MakeCallback(&OnRtsFailed));
  Config::ConnectWithoutContext(
    "/NodeList/*/ApplicationList/*/$ns3::UdpServer/Rx",
    MakeCallback(&OnRx));
}

void SetRtsThreshold(uint32_t thr) {
  Config::Set("/NodeList/*/DeviceList/*/$ns3::WifiNetDevice/RemoteStationManager/RtsCtsThreshold",
              UintegerValue(thr));
}

void AdaptTick() {
  uint64_t f = g_adaptFail - g_lastFail, s = g_adaptSucc - g_lastSucc;
  g_lastFail = g_adaptFail; g_lastSucc = g_adaptSucc;
  if (f + s >= g_minSamples) {
    double p = (double)f / (double)(f + s);
    g_pHat = g_pHatInit ? g_alpha * p + (1.0 - g_alpha) * g_pHat : p;
    g_pHatInit = true;
    // Enable RTS/CTS when expected airtime lost to collisions of the data frame
    // exceeds the fixed RTS/CTS overhead.
    bool want = (g_pHat * g_dataAirUs) > (g_margin * g_ovhUs);
    if (want != g_rtsOn) { g_rtsOn = want; SetRtsThreshold(want ? 0 : 65535); }
  }
  if (g_rtsOn && Measuring()) g_onTime += g_window;
  if (Simulator::Now().GetSeconds() + g_window < g_stop)
    Simulator::Schedule(Seconds(g_window), &AdaptTick);
}

void StartAdaptive(double window, double alpha, double margin, uint32_t minSamples,
                   double dataAirUs, double ovhUs, double start, double stop) {
  g_window = window; g_alpha = alpha; g_margin = margin; g_minSamples = minSamples;
  g_dataAirUs = dataAirUs; g_ovhUs = ovhUs; g_stop = stop;
  Simulator::Schedule(Seconds(start + window), &AdaptTick);
}

uint64_t RxPackets()   { return g_rxPackets; }
uint64_t RxBytes()     { return g_rxBytes; }
uint64_t DataFailed()  { return g_dataFailed; }
uint64_t RtsFailed()   { return g_rtsFailed; }
double RtsOnTime()     { return g_onTime; }
double MeanDelay()     { return g_delays.empty() ? 0.0 : g_delaySum / g_delays.size(); }
double P95Delay() {
  if (g_delays.empty()) return 0.0;
  std::vector<double> v = g_delays;
  std::sort(v.begin(), v.end());
  return v[(size_t)(0.95 * (v.size() - 1))];
}

}  // namespace htsim
"""


def load_helpers():
    if not hasattr(ns.cppyy.gbl, "htsim"):
        ns.cppyy.cppdef(CPP_HELPERS)
    return ns.cppyy.gbl.htsim


# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------
def control_rate(data_rate):
    """Highest mandatory 802.11a rate (6/12/24) not above the data rate."""
    return 24 if data_rate >= 24 else 12 if data_rate >= 12 else 6


def ofdm_airtime_us(psdu_bytes, rate_mbps):
    ndbps = rate_mbps * 4
    symbols = math.ceil((16 + 8 * psdu_bytes + 6) / ndbps)
    return 20 + 4 * symbols


def run_once(h, method, n, payload, a, run):
    h.Reset()
    h.SetWarmup(a.warmup)
    ns.RngSeedManager.SetSeed(a.seed)
    ns.RngSeedManager.SetRun(run)

    ap = ns.NodeContainer()
    ap.Create(1)
    stas = ns.NodeContainer()
    stas.Create(n)
    nodes = ns.NodeContainer()
    nodes.Add(ap)
    nodes.Add(stas)

    mobility = ns.MobilityHelper()
    mobility.SetMobilityModel("ns3::ConstantPositionMobilityModel")
    mobility.Install(nodes)

    # Channel: stations hear only the AP (positions are irrelevant here).
    channel = h.MakeChannel(nodes, a.link_loss_db, a.hidden_loss_db)
    phy = ns.YansWifiPhyHelper()
    phy.SetChannel(channel)

    ctrl = control_rate(a.phy_rate)
    threshold = RTS_ON if method == "rts-cts" else RTS_OFF
    wifi = ns.WifiHelper()
    wifi.SetStandard(ns.WIFI_STANDARD_80211a)
    wifi.SetRemoteStationManager(
        "ns3::ConstantRateWifiManager",
        "DataMode",
        ns.StringValue(f"OfdmRate{a.phy_rate}Mbps"),
        "ControlMode",
        ns.StringValue(f"OfdmRate{ctrl}Mbps"),
        "RtsCtsThreshold",
        ns.UintegerValue(threshold),
    )

    ssid = ns.Ssid("hidden-terminal")
    mac = ns.WifiMacHelper()
    mac.SetType(
        "ns3::StaWifiMac",
        "Ssid",
        ns.SsidValue(ssid),
        "ActiveProbing",
        ns.BooleanValue(False),
    )
    sta_devs = wifi.Install(phy, mac, stas)
    mac.SetType("ns3::ApWifiMac", "Ssid", ns.SsidValue(ssid))
    ap_dev = wifi.Install(phy, mac, ap)

    stack = ns.InternetStackHelper()
    stack.Install(nodes)

    addr = ns.Ipv4AddressHelper()
    addr.SetBase(ns.Ipv4Address("10.1.0.0"), ns.Ipv4Mask("255.255.0.0"))

    ap_if = addr.Assign(ap_dev)
    addr.Assign(sta_devs)

    # Traffic: every station -> AP, periodic UDP.
    server = ns.UdpServerHelper(UDP_PORT)
    server_apps = server.Install(ap.Get(0))
    server_apps.Start(ns.Seconds(0.0))
    server_apps.Stop(ns.Seconds(a.sim_time))

    interval_s = payload * 8 / (a.offered_load * 1e6)

    # ap_ip = ap_if.GetAddress(0)
    # server_address = ns.Address(ns.InetSocketAddress(ap_ip, UDP_PORT).ConvertTo())
    # client = ns.UdpClientHelper(server_address, UDP_PORT)
    client = ns.UdpClientHelper(
        ns.InetSocketAddress(ap_if.GetAddress(0), UDP_PORT).ConvertTo()
    )
    client.SetAttribute("MaxPackets", ns.UintegerValue(4294967295))
    client.SetAttribute("Interval", ns.TimeValue(ns.Seconds(interval_s)))
    client.SetAttribute("PacketSize", ns.UintegerValue(payload))
    rng = random.Random(a.seed * 100003 + run)
    for i in range(n):
        apps = client.Install(stas.Get(i))
        apps.Start(ns.Seconds(APP_START + rng.uniform(0.0, interval_s)))
        apps.Stop(ns.Seconds(a.sim_time))

    h.ConnectTraces()

    if method == "adaptive":
        data_air = ofdm_airtime_us(
            payload + 64, a.phy_rate
        )  # + UDP/IP/LLC/MAC overhead
        overhead = ofdm_airtime_us(20, ctrl) + ofdm_airtime_us(14, ctrl) + 2 * SIFS_US
        h.StartAdaptive(
            a.adapt_window,
            a.adapt_alpha,
            a.adapt_margin,
            a.adapt_min_samples,
            float(data_air),
            float(overhead),
            APP_START,
            a.sim_time,
        )

    ns.Simulator.Stop(ns.Seconds(a.sim_time))
    ns.Simulator.Run()

    measure_s = a.sim_time - a.warmup
    rx_pk = int(h.RxPackets())
    fails = int(h.DataFailed()) + int(h.RtsFailed())
    result = {
        "method": method,
        "nodes": n,
        "payload_bytes": payload,
        "offered_load_mbps": a.offered_load,
        "phy_rate_mbps": a.phy_rate,
        "sim_time_s": a.sim_time,
        "warmup_s": a.warmup,
        "run": run,
        "seed": a.seed,
        "throughput_mbps": int(h.RxBytes()) * 8 / measure_s / 1e6,
        "collision_rate": fails / (fails + rx_pk) if (fails + rx_pk) else 0.0,
        "mean_delay_ms": float(h.MeanDelay()) * 1e3,
        "p95_delay_ms": float(h.P95Delay()) * 1e3,
        "rx_packets": rx_pk,
        "data_failures": int(h.DataFailed()),
        "rts_failures": int(h.RtsFailed()),
        "rts_on_fraction": (float(h.RtsOnTime()) / measure_s)
        if method == "adaptive"
        else (1.0 if method == "rts-cts" else 0.0),
    }
    ns.Simulator.Destroy()
    return result


def parse_args():
    p = argparse.ArgumentParser(
        description="802.11 hidden-terminal simulation (CSMA/CA vs RTS/CTS vs adaptive).",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    p.add_argument(
        "--method",
        nargs="+",
        choices=METHODS + ["all"],
        default=["csma"],
        help="mitigation method(s); 'all' runs all three",
    )
    p.add_argument(
        "--nodes",
        nargs="+",
        type=int,
        default=[4],
        help="number of hidden stations (the AP is added separately)",
    )
    p.add_argument(
        "--payload",
        nargs="+",
        type=int,
        default=[512],
        help=f"UDP payload size(s) in bytes ({MIN_PAYLOAD}-{MAX_PAYLOAD})",
    )
    p.add_argument(
        "--offered-load",
        type=float,
        default=1.0,
        help="offered load PER STATION in Mbps (raise it to saturate)",
    )
    p.add_argument(
        "--phy-rate",
        type=int,
        choices=OFDM_RATES,
        default=6,
        help="802.11a/g constant data rate in Mbps",
    )
    p.add_argument(
        "--sim-time", type=float, default=20.0, help="total simulated seconds"
    )
    p.add_argument(
        "--warmup",
        type=float,
        default=2.0,
        help="seconds excluded from the statistics (must be > 1)",
    )
    p.add_argument(
        "--runs", type=int, default=3, help="independent runs per configuration"
    )
    p.add_argument(
        "--seed", type=int, default=1, help="RNG seed (run number varies the stream)"
    )
    p.add_argument(
        "--link-loss-db", type=float, default=50.0, help="STA<->AP path loss"
    )
    p.add_argument(
        "--hidden-loss-db",
        type=float,
        default=200.0,
        help="STA<->STA path loss (large = hidden)",
    )
    p.add_argument(
        "--adapt-window", type=float, default=0.5, help="adaptive: update period (s)"
    )
    p.add_argument(
        "--adapt-alpha", type=float, default=0.3, help="adaptive: EWMA weight"
    )
    p.add_argument(
        "--adapt-margin",
        type=float,
        default=1.0,
        help="adaptive: enable RTS when p*T_data > margin*T_overhead",
    )
    p.add_argument(
        "--adapt-min-samples",
        type=int,
        default=20,
        help="adaptive: min exchanges per window before updating",
    )
    p.add_argument(
        "--output",
        default="results/hidden_terminal.csv",
        help="CSV file (appended to; header written if new)",
    )
    a = p.parse_args()

    if "all" in a.method:
        a.method = METHODS
    if any(n < 2 for n in a.nodes):
        p.error("--nodes must be >= 2 to have hidden terminals")
    if any(not (MIN_PAYLOAD <= s <= MAX_PAYLOAD) for s in a.payload):
        p.error(f"--payload must be between {MIN_PAYLOAD} and {MAX_PAYLOAD}")
    if a.warmup <= APP_START or a.sim_time <= a.warmup:
        p.error(f"need warmup > {APP_START} and sim-time > warmup")
    return a


def main():
    a = parse_args()
    h = load_helpers()
    out = Path(a.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    new_file = not out.exists() or out.stat().st_size == 0

    configs = list(itertools.product(a.method, a.nodes, a.payload))
    rows = []
    t0 = time.time()
    with out.open("a", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_FIELDS)
        if new_file:
            writer.writeheader()
        for method, n, payload in configs:
            for run in range(1, a.runs + 1):
                r = run_once(h, method, n, payload, a, run)
                rows.append(r)
                writer.writerow(r)
                f.flush()
                print(
                    f"[{method:8s} n={n:<3d} pl={payload:<5d} run={run}] "
                    f"thr={r['throughput_mbps']:.3f} Mbps  "
                    f"coll={r['collision_rate']:.3f}  "
                    f"delay={r['mean_delay_ms']:.2f} ms",
                    flush=True,
                )

    print("\nSummary (mean over runs)")
    print(
        f"{'method':9s} {'nodes':>5s} {'payload':>7s} {'thr(Mbps)':>10s} "
        f"{'coll':>7s} {'delay(ms)':>10s}"
    )
    for method, n, payload in configs:
        grp = [
            r
            for r in rows
            if (r["method"], r["nodes"], r["payload_bytes"]) == (method, n, payload)
        ]
        print(
            f"{method:9s} {n:5d} {payload:7d} "
            f"{statistics.mean(r['throughput_mbps'] for r in grp):10.3f} "
            f"{statistics.mean(r['collision_rate'] for r in grp):7.3f} "
            f"{statistics.mean(r['mean_delay_ms'] for r in grp):10.2f}"
        )
    print(f"\nWrote {len(rows)} rows to {out} in {time.time() - t0:.1f} s")


if __name__ == "__main__":
    sys.exit(main())
