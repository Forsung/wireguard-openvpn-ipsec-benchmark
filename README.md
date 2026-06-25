#Reproducibility Repository

Project: **Performance and Security Evaluation of WireGuard, OpenVPN and IPsec as Enterprise Remote Access Solutions**.

This repository contains the scripts, configuration templates, and analysis tools used in the project experiments. The testbed compares **WireGuard**, **OpenVPN**, and **IPsec (strongSwan)** across multiple client platforms and access-network conditions.

## What is evaluated

The project measures:

- throughput
- latency / RTT
- jitter
- packet loss
- CPU and memory usage
- handshake time
- reconnect time
- MTU / fragmentation behavior
- mobility behavior
- throughput-per-CPU efficiency
- security-relevant cryptographic design and packet protection

## Testbed summary

The experimental environment uses:

- a **CSC cPouta VPS** as the public VPN gateway
- a **VirtualBox Ubuntu VM (x86)** as one client
- a **Raspberry Pi 4 (ARM)** as another client
- a **WSL client** on the orchestrator laptop
- a **consumer TP-Link dual-band router** for NAT and Wi‑Fi variability

The main comparison uses the **5 GHz** band. A separate baseline comparison is run on **2.4 GHz**.

## Repository contents

- `scripts/`  
  Automation scripts for running the staged experiment matrix and collecting results.

- `configs/`  
  Sanitized configuration templates for WireGuard, OpenVPN, and IPsec.

- `analysis scripts/`  
  Python scripts for extracting and plotting results.

- `.gitignore/`  
   - analysis: Figures (boxplot figures after plot script) and output (CSV result file after extraction sctipt run)
   - results: Raw run folders produced by the staged experiments script.

- `setup guide/`  
  Commands used for each testbed device.

## Experimental stages

The staged matrix includes:

- Baseline
- Latency
- Packet loss
- MTU variation
- CPU stress
- Mobility / reconnect

Each run produces a separate output folder containing:

- `metadata.json`
- `ping.log`
- `iperf_tcp.json`
- `iperf_udp.json`
- `cpu.json`
- protocol state snapshots (`wg_show.txt`, `openvpn_status.txt`, `ipsec_status.txt`)
- `handshake_ms.txt`
- `reconnect_ms.txt`
- optional `capture.pcap` (I commented out capture.pcap in the test_run.py script due to lack of storage during capture so uncomment if needed when reproducing)

## Reproducibility workflow

1. Prepare the server and clients.
2. Install VPN software and measurement tools.
3. Run the staged matrix scripts.
4. Extract results into CSV format.
5. Aggregate the measurements if needed.
6. Generate thesis figures from the outputs.

## Security evaluation note

The project discussion includes a security-evaluation subsection focused on the cryptographic design of WireGuard, OpenVPN, and IPsec: key exchange, cipher selection, and packet protection.

## Notes

- This repository contains **sanitized** templates only.
- Private keys, secrets, and large raw measurement archives are excluded from version control.

## Example usage

```bash
./scripts/run_staged_matrix.sh vm 5GHz all
./scripts/run_staged_matrix.sh pi 2.4GHz mobility
python3 "analysis scripts/extract_results.py"
python3 "analysis scripts/plot_results.py"
```

## Expected usage

The repository is intended to support:

1. Reproducibility
2. Experiment reruns
3. Result verification
4. Future extension of the methodology
