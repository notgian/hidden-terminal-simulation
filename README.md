# hidden-terminal-simulation

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
    git clone <repository-url> hidden-terminal-simulation
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
    git clone <repository-url> hidden-terminal-simulation
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

```bash
docker compose run --rm sim python simulations/<script>.py
```

## Project Structure

```
simulations/   ns-3 scenario scripts
results/        simulation output (gitignored)
```

## License

TODO
