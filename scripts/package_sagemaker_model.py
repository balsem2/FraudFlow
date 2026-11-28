"""Package the trained model in the layout SageMaker extracts under /opt/ml/model."""
import argparse
import tarfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", type=Path, default=ROOT / "artifacts" / "model.joblib")
    parser.add_argument(
        "--output", type=Path, default=ROOT / "artifacts" / "sagemaker" / "model.tar.gz"
    )
    args = parser.parse_args()
    model_path = args.model.resolve()
    output_path = args.output.resolve()
    if not model_path.is_file():
        parser.error(f"Model file not found: {model_path}")
    output_path.parent.mkdir(parents=True, exist_ok=True)

    with tarfile.open(output_path, "w:gz") as archive:
        archive.add(model_path, arcname="model.joblib")
    print(f"Packaged model: {output_path}")


if __name__ == "__main__":
    main()
