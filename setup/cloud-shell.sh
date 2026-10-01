# Безключове підключення GitHub → Google Cloud для відеотеки.
# Вставте цей блок цілком у Cloud Shell (кнопка >_ угорі консолі Google Cloud) і натисніть Enter.
# Назви (display-name) лише латиницею: Google обмежує їх 32 байтами, а кирилиця займає вдвічі більше.
# Виконується один раз. Команди безпечно запускати повторно: якщо щось уже створено,
# з'явиться повідомлення «already exists», і це нормально.

PROJECT_ID=videotekachl
PROJECT_NUMBER=72740842734
REPO=t-a-yaku/nbukids-video        # після перенесення репозиторію: див. блок «Якщо репозиторій перенесено» в кінці файлу
ROBOT=videoteka-reader@${PROJECT_ID}.iam.gserviceaccount.com

gcloud config set project "$PROJECT_ID"

# 1. Сервіси, потрібні для безключового входу
gcloud services enable iamcredentials.googleapis.com sts.googleapis.com sheets.googleapis.com

# 2. «Пул довіри» для GitHub
gcloud iam workload-identity-pools create github \
  --location=global --display-name="GitHub"

# 3. Довіряємо лише одному репозиторію відеотеки
gcloud iam workload-identity-pools providers create-oidc github-repo \
  --location=global --workload-identity-pool=github --display-name="Videoteka repo" \
  --issuer-uri="https://token.actions.githubusercontent.com" \
  --attribute-mapping="google.subject=assertion.sub,attribute.repository=assertion.repository" \
  --attribute-condition="assertion.repository=='${REPO}'"

# 4. Дозволяємо цьому репозиторію діяти від імені робота (і тільки йому)
gcloud iam service-accounts add-iam-policy-binding "$ROBOT" \
  --role=roles/iam.workloadIdentityUser \
  --member="principalSet://iam.googleapis.com/projects/${PROJECT_NUMBER}/locations/global/workloadIdentityPools/github/attribute.repository/${REPO}"

echo "Готово. Провайдер: projects/${PROJECT_NUMBER}/locations/global/workloadIdentityPools/github/providers/github-repo"

# ── Якщо репозиторій перенесено або перейменовано ──────────────────────────────
# Замініть НОВА/НАЗВА на нову адресу репозиторію (наприклад, chl-kiev-ua/videoteka) і виконайте:
#
# NEW_REPO=НОВА/НАЗВА
# gcloud iam workload-identity-pools providers update-oidc github-repo \
#   --project=videotekachl --location=global --workload-identity-pool=github \
#   --attribute-condition="assertion.repository=='${NEW_REPO}'"
# gcloud iam service-accounts add-iam-policy-binding videoteka-reader@videotekachl.iam.gserviceaccount.com \
#   --role=roles/iam.workloadIdentityUser \
#   --member="principalSet://iam.googleapis.com/projects/72740842734/locations/global/workloadIdentityPools/github/attribute.repository/${NEW_REPO}"
# Старий дозвіл для попередньої назви після цього можна видалити в IAM робота.
