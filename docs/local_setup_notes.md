# Local Setup Notes

## Large model files

The following files are required to run the ML pipeline locally but are not committed to GitHub because they are larger than GitHub's normal file size limit:

- `ml-service/mdv5a.pt`
- `ml-service/model.pt`

Each team member must manually place these files inside the `ml-service/` folder before running the ML script.

Expected structure:

```text
ml-service/
├── batch.py
├── config.yaml
├── labels.txt
├── requirements.txt
├── mdv5a.pt
├── model.pt
└── images/