from pathlib import Path
from typing import Dict, List, Tuple

import torch
import torchvision.transforms as transforms
from PIL import Image
import numpy as np

# supported classes in the model
classes = ['Alectura_lathami', 'Antechinus_agilis', 'Bos_taurus', 'Burhinus_grallarius', 'Canis_familiaris', 'Chalcophaps_longirostris', 'Colluricincla_harmonica', 'Corcorax_melanorhamphos', 'Dacelo_novaeguineae', 'Dama_dama', 'Eopsaltria_australis', 'Felis_catus', 'Geopelia_humeralis', 'Gymnorhina_tibicen', 'Homo_sapiens', 'Isoodon_macrourus', 'Lepus_europaeus', 'Macropus_giganteus', 'Menura_novaehollandiae', 'Mus_musculus', 'Oryctolagus_cuniculus', 'Perameles_nasuta', 'Pitta_versicolor', 'Rattus', 'Rattus_fuscipes', 'Rattus_rattus', 'Strepera_graculina', 'Sus_scrofa', 'Tachyglossus_aculeatus', 'Thylogale_stigmatica', 'Trichosurus_caninus', 'Trichosurus_cunninghami', 'Trichosurus_vulpecula', 'Varanus_varius', 'Vombatus_ursinus', 'Vulpes_vulpes', 'Wallabia_bicolor', 'Canis_dingo', 'Capra_hircus', 'Casuarius_casuarius', 'Heteromyias_cinereifrons', 'Hypsiprymnodon_moschatus', 'Megapodius_reinwardt', 'Notamacropus_rufogriseus', 'Orthonyx_spaldingii', 'Uromys_caudimaculatus']

def get_device() -> str:
    if torch.cuda.is_available():
        return "cuda"
    elif torch.backends.mps.is_available():
        return "mps"
    else:
        return "cpu"
    
transform = transforms.Compose([
    transforms.Resize((480, 480)),
    transforms.ToTensor(),
])


def load_species_model(model_path: str = "model.pt"):
    device = get_device()

    model = torch.load(model_path, map_location=device, weights_only=False)
    model.eval()
    model.to(device)

    return model, device


@torch.no_grad()
def classify_crop(image_path: str, model, device: str) -> Dict[str, object]:
    img = Image.open(image_path).convert("RGB")

    img = transform(img)
    img = img.unsqueeze(0)
    img = img.permute(0, 2, 3, 1)
    img = img.to(device)

    logits = model(img)
    probs = torch.softmax(logits, dim=1)[0].cpu().numpy()

    best_idx = int(np.argmax(probs))
    best_label = classes[best_idx]
    confidence = float(probs[best_idx])

    return {
        "species": best_label,
        "confidence": confidence
    }


def classify_crops_in_folder(
    crop_folder: str = "cropped_images",
    model_path: str = "model.pt"
) -> List[Dict[str, object]]:
    model, device = load_species_model(model_path)

    crop_paths = sorted(Path(crop_folder).glob("*"))

    results = []

    for crop_path in crop_paths:
        if crop_path.suffix.lower() not in [".jpg", ".jpeg", ".png"]:
            continue

        prediction = classify_crop(str(crop_path), model, device)

        results.append({
            "crop_path": str(crop_path),
            "species": prediction["species"],
            "confidence": prediction["confidence"]
        })

    return results

def count_species_tags(
    predictions: List[Dict[str, object]],
    min_confidence: float = 0.5
) -> Dict[str, int]:
    tag_counts = {}

    for prediction in predictions:
        species = prediction["species"]
        confidence = prediction["confidence"]

        if confidence < min_confidence:
            continue

        tag_counts[species] = tag_counts.get(species, 0) + 1

    return tag_counts


def generate_tags_from_crops(
    crop_folder: str = "cropped_images",
    model_path: str = "model.pt",
    min_confidence: float = 0.5
) -> Dict[str, int]:
    predictions = classify_crops_in_folder(
        crop_folder=crop_folder,
        model_path=model_path
    )

    tags = count_species_tags(
        predictions=predictions,
        min_confidence=min_confidence
    )

    return tags