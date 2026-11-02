# Hidden Terminal Simulation Project

**Working title:** A Comparative Performance Analysis of MAC-layer Hidden Terminal Mitigation Techniques in IEEE 802.11 Across Varying Payload Sizes

## Requirements and Dependencies

| Requirement                                       | Notes                                                       |
| ------------------------------------------------- | ----------------------------------------------------------- |
| [Docker](https://docs.docker.com/get-docker/)     | Recommended on all platforms; required on Windows and macOS |
| [Python 3.12](https://www.python.org/)            | Installed and managed automatically by uv                   |
| [uv](https://docs.astral.sh/uv/)                  | Package and project manager                                 |
| [ns3 (PyPI wheel)](https://pypi.org/project/ns3/) | Pre-compiled ns-3 with Python bindings (Linux only)         |
| C++ compiler (g++)                                | Needed by cppyy at runtime; included in the Docker image    |

Python dependencies (numpy, pandas, matplotlib, ns3) are declared in
`pyproject.toml` and locked in `uv.lock`.

> **Platform note:** the pre-compiled `ns3` wheel is only available for Linux.
> On Windows and macOS, run everything through Docker.

## Installation

### Option A: Docker (recommended, all platforms)

1. Install Docker:
    - **Windows / macOS:** install [Docker Desktop](https://www.docker.com/products/docker-desktop/) (Windows: enable the WSL2 backend).
    - **Ubuntu:** `sudo apt install docker.io docker-compose-v2`
    - **CachyOS / Arch:** `sudo pacman -S docker docker-compose`
    - On Linux, then run `sudo systemctl enable --now docker` and
      `sudo usermod -aG docker $USER` (log out and back in).
2. Clone the repository:
    ```bash
    # or clone with ssh if you want
    git clone https://github.com/notgian/hidden-terminal-simulation hidden-terminal-simulation
    cd hidden-terminal-simulation
    ```
3. Build the image and run the installation test
    ```bash
    docker compose build
    docker compose run --rm sim
    ```
4. Run any simulation script:
    ```bash
    docker compose run --rm sim python simulations/<script>.py
    ```
    Results are written to `./results/`.

### Option B: Native (Linux only)

1. Install a C++ compiler and uv:
    - **Ubuntu:** `sudo apt install build-essential curl`
    - **CachyOS / Arch:** `sudo pacman -S base-devel uv`
    - uv (any Linux): `curl -LsSf https://astral.sh/uv/install.sh | sh`
2. Clone the repository and install dependencies:
    ```bash
    # or clone with ssh if you want
    git clone https://github.com/notgian/hidden-terminal-simulation hidden-terminal-simulation
    cd hidden-terminal-simulation
    uv sync
    ```
3. Verify the installation:
    ```bash
    uv run python simulations/check_ns3_installation.py
    ```

### Troubleshooting

- **Apple Silicon:** if the wheel is unavailable for arm64, add
  `platform: linux/amd64` to the `sim` service in `compose.yaml`.

## Usage

To run any script, use the following command:

```bash
docker compose run --rm sim python simulations/<script>.py
```

### Installation Check

A simple check script to ensure that the installation is succesful. Run it with:

```bash
docker compose run --rm sim python simulations/check_ns3_installation.py
```

You should see an output similar to this:

```
Created 3 nodes
Simulated time: 1.0 s
ns-3 OK
```

### Hidden Terminal Script

Simulates the hidden terminal situation given the parameters in its run command:

```bash
docker compose run --rm sim python simulations/hidden_terminal.py \
    --method csma --nodes 3 --payload 512 --sim-time 5 --warmup 2 --runs 1
```

| Flag                                 | Meaning                                                                   |
| :----------------------------------- | :------------------------------------------------------------------------ |
| `--method`                           | One or more access schemes: `csma`, `rts-cts`, `adaptive`, or `all`       |
| `--nodes`                            | One or more counts of hidden stations (the AP is extra)                   |
| `--payload`                          | One or more UDP payload sizes, 12–1472 bytes                              |
| `--offered-load`                     | Per-station load in Mbps; raise to saturate the channel                   |
| `--phy-rate`                         | Fixed 802.11a/g data rate (default: `6 Mbps`)                             |
| `--runs`, `--seed`                   | Independent runs per configuration and base random seed                   |
| `--sim-time`, `--warmup`             | Total simulation duration and excluded start-up period (seconds)          |
| `--adapt-*`                          | Controller knobs for the adaptive RTS/CTS scheme                          |
| `--link-loss-db`, `--hidden-loss-db` | Channel path loss (dB) between stations and AP, and between station pairs |

_Note: Flags like `--method`, `--nodes`, and `--payload` accept space-separated lists. The script runs all combinatorial permutations of supplied parameters._

#### Varying Payload Sizes

Run the hidden terminal simulation across multiple payload sizes:

```bash
docker compose run --rm sim python simulations/hidden_terminal.py \
    --method all --nodes 4 --payload 64 256 512 1024 1472 \
    --offered-load 3 --sim-time 20 --runs 5
```

#### Varying Number of Hidden Terminals

Run the simulation varying the count of hidden stations:

```bash
docker compose run --rm sim python simulations/hidden_terminal.py \
    --method all --nodes 2 4 8 16 --payload 1472 --offered-load 3 --runs 5
```

## Project Structure

```
simulations/   ns-3 scenario scripts
results/        simulation output (gitignored)
```
