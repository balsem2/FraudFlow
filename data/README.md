# BankSim dataset

This directory contains `banksim.csv`, the synthetic BankSim payment dataset.
It also contains a compressed copy of the generated investigation examples.

- Source: [Synthetic data from a financial payment system](https://www.kaggle.com/datasets/ealaxi/banksim1), distributed by Kaggle user `ealaxi`.
- License: [CC BY-NC-SA 4.0](https://creativecommons.org/licenses/by-nc-sa/4.0/).

The dataset is included for non-commercial educational use with attribution.
Redistributions and adaptations must comply with the license terms, including
the non-commercial and share-alike requirements. The model artifacts in
`artifacts/` were trained using this dataset and are provided for this project.
`investigation_synthetic.jsonl` is generated from BankSim and contains simulated
security context and scenario labels, not real causal ground truth. The generated
dataset and published evaluation metrics are shared under the same conditions.

To unpack the investigation examples in PowerShell:

```powershell
Expand-Archive -Path .\data\investigation_synthetic.jsonl.zip -DestinationPath .\data -Force
```
