#!/usr/bin/env bash
#
# OpenPaw Process Manager
# Manage OpenPaw agent workspaces with start/stop/restart/status commands
#

set -euo pipefail

# Project root is parent of scripts directory
PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CONFIG_FILE="${PROJECT_ROOT}/config.yaml"
LOGS_DIR="${PROJECT_ROOT}/logs"
PID_FILE="${LOGS_DIR}/openpaw.pid"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Create logs directory if it doesn't exist
mkdir -p "${LOGS_DIR}"

# Print colored message
print_status() {
    local color=$1
    shift
    echo -e "${color}$*${NC}"
}

# Print usage information
usage() {
    cat << EOF
Usage: $(basename "$0") <command> [options]

Commands:
    start [workspace] [-v]  Start OpenPaw (optionally with specific workspace)
                            Use -v flag for verbose output
    stop                    Stop all running OpenPaw processes gracefully
    restart [workspace]     Stop then start (optionally with specific workspace)
    status                  Show if OpenPaw is running and which workspaces
    logs [workspace]        Tail logs (default: openpaw.log, or workspace-specific)
    kill                    Force kill all OpenPaw processes
    clear-logs              Clear all log files

Examples:
    $(basename "$0") start krieger -v    # Start krieger workspace with verbose logging
    $(basename "$0") start --all         # Start all workspaces
    $(basename "$0") stop                # Stop gracefully
    $(basename "$0") restart             # Restart with same arguments
    $(basename "$0") logs krieger        # Tail krieger workspace logs
    $(basename "$0") status              # Check running status

EOF
    exit 1
}

# Check if OpenPaw is running
is_running() {
    if [[ -f "${PID_FILE}" ]]; then
        local pid
        pid=$(cat "${PID_FILE}")
        if ps -p "${pid}" > /dev/null 2>&1; then
            return 0
        else
            # Stale PID file
            rm -f "${PID_FILE}"
            return 1
        fi
    fi
    return 1
}

# Get current PID
get_pid() {
    if [[ -f "${PID_FILE}" ]]; then
        cat "${PID_FILE}"
    fi
}

# Get workspace from saved arguments
get_workspace() {
    local args_file="${LOGS_DIR}/last_args.txt"
    if [[ -f "${args_file}" ]]; then
        cat "${args_file}"
    fi
}

# Start OpenPaw
cmd_start() {
    local workspace=""
    local verbose=""
    local extra_args=""

    # Parse arguments
    while [[ $# -gt 0 ]]; do
        case $1 in
            -v|--verbose)
                verbose="-v"
                shift
                ;;
            --all)
                extra_args="--all"
                shift
                ;;
            *)
                workspace="$1"
                shift
                ;;
        esac
    done

    # Check if already running
    if is_running; then
        print_status "${YELLOW}" "OpenPaw is already running with PID $(get_pid)"
        print_status "${YELLOW}" "Use 'stop' or 'restart' to change workspaces"
        return 1
    fi

    # Build command
    local cmd="cd ${PROJECT_ROOT} && poetry run openpaw -c ${CONFIG_FILE}"

    if [[ -n "${extra_args}" ]]; then
        cmd="${cmd} ${extra_args}"
    elif [[ -n "${workspace}" ]]; then
        cmd="${cmd} -w ${workspace}"
    fi

    if [[ -n "${verbose}" ]]; then
        cmd="${cmd} ${verbose}"
    fi

    # Determine log file
    local log_file="${LOGS_DIR}/openpaw.log"
    if [[ -n "${workspace}" && "${workspace}" != "--all" ]]; then
        log_file="${LOGS_DIR}/${workspace}.log"
    fi

    print_status "${BLUE}" "Starting OpenPaw..."
    print_status "${BLUE}" "Command: ${cmd}"
    print_status "${BLUE}" "Log file: ${log_file}"

    # Save command arguments for restart
    local args_str=""
    [[ -n "${workspace}" ]] && args_str="${workspace}"
    [[ -n "${extra_args}" ]] && args_str="${extra_args}"
    [[ -n "${verbose}" ]] && args_str="${args_str} ${verbose}"
    echo "${args_str}" > "${LOGS_DIR}/last_args.txt"

    # Start process in background
    nohup bash -c "${cmd}" > "${log_file}" 2>&1 &
    local pid=$!

    # Save PID
    echo "${pid}" > "${PID_FILE}"

    # Wait a moment and check if it's still running
    sleep 2
    if ps -p "${pid}" > /dev/null 2>&1; then
        print_status "${GREEN}" "✓ OpenPaw started successfully (PID: ${pid})"
        print_status "${GREEN}" "  Tail logs: $(basename "$0") logs ${workspace}"
    else
        print_status "${RED}" "✗ OpenPaw failed to start. Check logs: ${log_file}"
        rm -f "${PID_FILE}"
        return 1
    fi
}

# Stop OpenPaw gracefully
cmd_stop() {
    if ! is_running; then
        print_status "${YELLOW}" "OpenPaw is not running"
        return 0
    fi

    local pid
    pid=$(get_pid)
    print_status "${BLUE}" "Stopping OpenPaw (PID: ${pid})..."

    # Send SIGTERM for graceful shutdown
    kill -TERM "${pid}" 2>/dev/null || true

    # Wait up to 10 seconds for graceful shutdown
    local count=0
    while ps -p "${pid}" > /dev/null 2>&1 && [[ ${count} -lt 10 ]]; do
        sleep 1
        ((count++))
    done

    # Check if process stopped
    if ps -p "${pid}" > /dev/null 2>&1; then
        print_status "${YELLOW}" "Process did not stop gracefully, sending SIGKILL..."
        kill -KILL "${pid}" 2>/dev/null || true
        sleep 1
    fi

    # Clean up PID file
    rm -f "${PID_FILE}"

    if ps -p "${pid}" > /dev/null 2>&1; then
        print_status "${RED}" "✗ Failed to stop OpenPaw"
        return 1
    else
        print_status "${GREEN}" "✓ OpenPaw stopped successfully"
    fi
}

# Force kill all OpenPaw processes
cmd_kill() {
    print_status "${BLUE}" "Force killing all OpenPaw processes..."

    # Kill by PID file first
    if [[ -f "${PID_FILE}" ]]; then
        local pid
        pid=$(cat "${PID_FILE}")
        kill -KILL "${pid}" 2>/dev/null || true
    fi

    # Kill any stray processes
    pkill -9 -f "openpaw" || true

    # Clean up PID file
    rm -f "${PID_FILE}"

    print_status "${GREEN}" "✓ All OpenPaw processes killed"
}

# Show status
cmd_status() {
    if is_running; then
        local pid
        pid=$(get_pid)
        print_status "${GREEN}" "✓ OpenPaw is running (PID: ${pid})"

        # Show process info
        print_status "${BLUE}" "\nProcess info:"
        ps -p "${pid}" -o pid,ppid,user,%cpu,%mem,etime,command | tail -n +2

        # Show last arguments
        if [[ -f "${LOGS_DIR}/last_args.txt" ]]; then
            local args
            args=$(cat "${LOGS_DIR}/last_args.txt")
            [[ -n "${args}" ]] && print_status "${BLUE}" "\nLast arguments: ${args}"
        fi

        # Show log files
        print_status "${BLUE}" "\nLog files:"
        ls -lh "${LOGS_DIR}"/*.log 2>/dev/null | awk '{print "  " $9 " (" $5 ")"}'
    else
        print_status "${YELLOW}" "✗ OpenPaw is not running"
    fi
}

# Tail logs
cmd_logs() {
    local workspace="${1:-}"
    local log_file="${LOGS_DIR}/openpaw.log"

    if [[ -n "${workspace}" ]]; then
        log_file="${LOGS_DIR}/${workspace}.log"
    fi

    if [[ ! -f "${log_file}" ]]; then
        print_status "${RED}" "Log file not found: ${log_file}"
        print_status "${YELLOW}" "Available logs:"
        ls -1 "${LOGS_DIR}"/*.log 2>/dev/null | xargs -n1 basename || print_status "${YELLOW}" "  (no logs found)"
        return 1
    fi

    print_status "${BLUE}" "Tailing ${log_file} (Ctrl+C to exit)..."
    tail -f "${log_file}"
}

# Clear logs
cmd_clear_logs() {
    print_status "${BLUE}" "Clearing all log files..."
    rm -f "${LOGS_DIR}"/*.log
    print_status "${GREEN}" "✓ Log files cleared"
}

# Restart OpenPaw
cmd_restart() {
    local args=("$@")

    # If no arguments provided, use last saved arguments
    if [[ ${#args[@]} -eq 0 && -f "${LOGS_DIR}/last_args.txt" ]]; then
        local saved_args
        saved_args=$(cat "${LOGS_DIR}/last_args.txt")
        if [[ -n "${saved_args}" ]]; then
            print_status "${BLUE}" "Restarting with saved arguments: ${saved_args}"
            # shellcheck disable=SC2086
            read -ra args <<< "${saved_args}"
        fi
    fi

    cmd_stop
    sleep 2
    cmd_start "${args[@]}"
}

# Main command router
main() {
    if [[ $# -lt 1 ]]; then
        usage
    fi

    local command=$1
    shift

    case "${command}" in
        start)
            cmd_start "$@"
            ;;
        stop)
            cmd_stop "$@"
            ;;
        restart)
            cmd_restart "$@"
            ;;
        status)
            cmd_status "$@"
            ;;
        logs)
            cmd_logs "$@"
            ;;
        kill)
            cmd_kill "$@"
            ;;
        clear-logs)
            cmd_clear_logs "$@"
            ;;
        -h|--help|help)
            usage
            ;;
        *)
            print_status "${RED}" "Unknown command: ${command}"
            echo
            usage
            ;;
    esac
}

main "$@"
