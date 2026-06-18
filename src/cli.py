"""
CLI interface for the Multi-Agent AI Test Engineer System.

Usage:
    python -m src.cli --requirement "Your requirement here"
    python -m src.cli --interactive
    python -m src.cli --demo
"""
import argparse
import json
import logging
import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.orchestrator.workflow import Orchestrator, MockOrchestrator
from src.memory.storage import MemoryStorage
from src.adapters.llm_adapter import LLMAdapter

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


def setup_logging(verbose: bool = False) -> None:
    """Setup logging configuration."""
    level = logging.DEBUG if verbose else logging.INFO
    logging.getLogger().setLevel(level)


def print_section(title: str) -> None:
    """Print a section header."""
    print("\n" + "=" * 60)
    print(f" {title}")
    print("=" * 60 + "\n")


def print_json(data: dict, indent: int = 2) -> None:
    """Print data as formatted JSON."""
    print(json.dumps(data, ensure_ascii=False, indent=indent))


def run_requirement(
    orchestrator: Orchestrator,
    requirement: str,
    verbose: bool = False
) -> dict:
    """
    Run the workflow with a single requirement.

    Args:
        orchestrator: The workflow orchestrator
        requirement: The requirement string
        verbose: Whether to print verbose output

    Returns:
        The workflow result
    """
    print_section("Processing Requirement")
    print(f"Requirement: {requirement}\n")

    result = orchestrator.run(requirement)

    if result["status"] == "needs_clarification":
        print_section("Clarification Required")
        print("The following questions need to be answered:\n")
        for i, q in enumerate(result["questions"], 1):
            print(f"  {i}. {q}")
        print("\n")
        return result

    elif result["status"] == "error":
        print_section("Error")
        print(f"Error: {result.get('error')}\n")
        return result

    # Print results
    print_section("Results")

    if result.get("pm_output"):
        print("PM Parsed Requirements:")
        print_json(result["pm_output"])
        print()

    if result.get("test_cases"):
        print("Generated Test Cases:")
        print_json(result["test_cases"])

    return result


def interactive_mode(orchestrator: Orchestrator) -> None:
    """Run in interactive mode."""
    print_section("Multi-Agent AI Test Engineer System")
    print("Interactive Mode")
    print("Enter your requirements and the system will generate test cases.")
    print("Type 'quit' or 'exit' to exit.\n")

    while True:
        try:
            requirement = input("\nEnter requirement (or 'quit' to exit):\n> ")

            if requirement.lower() in ["quit", "exit", "q"]:
                print("Exiting...")
                break

            if not requirement.strip():
                continue

            result = run_requirement(orchestrator, requirement)

            if result["status"] == "needs_clarification":
                print("\nPlease provide answers to the questions above.")
                print("For now, we'll skip to demo mode...\n")
                break

        except KeyboardInterrupt:
            print("\n\nInterrupted. Exiting...")
            break
        except Exception as e:
            print(f"\nError: {e}\n")


def demo_mode(orchestrator: Orchestrator) -> None:
    """Run a demo with sample requirements."""
    print_section("Demo Mode")

    demo_requirements = [
        "用户登录系统时，需要输入用户名和密码，系统验证通过后跳转到首页。如果连续5次输入错误密码，账户将被锁定30分钟。",
    ]

    for i, req in enumerate(demo_requirements, 1):
        print(f"\n--- Demo {i} ---\n")
        result = run_requirement(orchestrator, req)

        if result["status"] == "needs_clarification":
            # Auto-answer for demo
            print("Questions need answering - ending demo here")
            break

        # Small delay between demos
        import time
        time.sleep(0.5)


def main() -> int:
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Multi-Agent AI Test Engineer System",
        formatter_class=argparse.RawDescriptionHelpFormatter
    )

    parser.add_argument(
        "--requirement", "-r",
        type=str,
        help="Process a single requirement"
    )

    parser.add_argument(
        "--interactive", "-i",
        action="store_true",
        help="Run in interactive mode"
    )

    parser.add_argument(
        "--demo",
        action="store_true",
        help="Run demo with sample requirements"
    )

    parser.add_argument(
        "--mock",
        action="store_true",
        help="Use mock agents (no LLM calls)"
    )

    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Enable verbose output"
    )

    parser.add_argument(
        "--stats",
        action="store_true",
        help="Show memory storage statistics"
    )

    parser.add_argument(
        "--reset",
        action="store_true",
        help="Reset the workflow state"
    )

    args = parser.parse_args()

    setup_logging(args.verbose)

    # Initialize storage
    storage = MemoryStorage()

    # Show stats and exit if requested
    if args.stats:
        print_section("Memory Storage Statistics")
        stats = storage.get_stats()
        print_json(stats)
        return 0

    # Initialize orchestrator
    if args.mock:
        logger.info("Using Mock Orchestrator")
        orchestrator = MockOrchestrator(memory_storage=storage)
    else:
        orchestrator = Orchestrator(memory_storage=storage)

    # Reset if requested
    if args.reset:
        orchestrator.reset()
        print("Workflow state reset.")
        return 0

    # Run based on mode
    try:
        if args.requirement:
            result = run_requirement(orchestrator, args.requirement)
            return 0 if result["status"] == "success" else 1

        elif args.interactive:
            interactive_mode(orchestrator)

        elif args.demo:
            demo_mode(orchestrator)

        else:
            parser.print_help()
            return 1

    except Exception as e:
        logger.error(f"Error: {e}", exc_info=True)
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())