/**
 * Seed script to populate Firestore with 10,000 valid participant IDs.
 *
 * Usage:
 *   1. Make sure you're logged in: firebase login
 *   2. Run: npm run seed
 */

import { initializeApp, cert } from 'firebase-admin/app';
import { getFirestore } from 'firebase-admin/firestore';
import { execSync } from 'child_process';
import { readFileSync, existsSync } from 'fs';

const PROJECT_ID = 'r01-redditx-suicide';
const COLLECTION = 'valid_participants';
const TOTAL_IDS = 10000;
const BATCH_SIZE = 500; // Firestore batch limit

/**
 * Get Firebase access token using firebase CLI
 */
function getFirebaseToken() {
  try {
    // Use firebase CLI to get access token
    const result = execSync('firebase --project r01-redditx-suicide login:ci --no-localhost 2>/dev/null || firebase auth:export --project r01-redditx-suicide 2>&1 | head -1', {
      encoding: 'utf8'
    });
    return result.trim();
  } catch (e) {
    return null;
  }
}

/**
 * Generate a 9-digit participant ID with leading zeros
 */
function generateParticipantId(num) {
  return String(num).padStart(9, '0');
}

/**
 * Initialize Firebase Admin using service account from environment
 * or fallback to application default credentials
 */
async function initializeFirebase() {
  // Check for service account key file
  const serviceAccountPath = process.env.GOOGLE_APPLICATION_CREDENTIALS;

  if (serviceAccountPath && existsSync(serviceAccountPath)) {
    console.log('Using service account from GOOGLE_APPLICATION_CREDENTIALS');
    const serviceAccount = JSON.parse(readFileSync(serviceAccountPath, 'utf8'));
    initializeApp({
      credential: cert(serviceAccount),
      projectId: PROJECT_ID,
    });
  } else {
    // Try using the gcloud credentials file location
    const homeDir = process.env.HOME;
    const gcloudCredPath = `${homeDir}/.config/gcloud/application_default_credentials.json`;

    if (existsSync(gcloudCredPath)) {
      console.log('Using gcloud application default credentials');
      process.env.GOOGLE_APPLICATION_CREDENTIALS = gcloudCredPath;
      const { applicationDefault } = await import('firebase-admin/app');
      initializeApp({
        credential: applicationDefault(),
        projectId: PROJECT_ID,
      });
    } else {
      console.error(`
No credentials found. Please do one of the following:

Option 1: Download service account key
  1. Go to Firebase Console > Project Settings > Service Accounts
  2. Click "Generate new private key"
  3. Save the JSON file and run:
     GOOGLE_APPLICATION_CREDENTIALS=/path/to/key.json npm run seed

Option 2: Install gcloud CLI and authenticate
  1. Install: https://cloud.google.com/sdk/docs/install
  2. Run: gcloud auth application-default login
  3. Then run: npm run seed
`);
      process.exit(1);
    }
  }

  return getFirestore();
}

/**
 * Seed participant IDs to Firestore in batches
 */
async function seedParticipants() {
  const db = await initializeFirebase();

  console.log(`Starting to seed ${TOTAL_IDS} participant IDs...`);

  let totalWritten = 0;

  for (let batchStart = 1; batchStart <= TOTAL_IDS; batchStart += BATCH_SIZE) {
    const batch = db.batch();
    const batchEnd = Math.min(batchStart + BATCH_SIZE - 1, TOTAL_IDS);

    for (let i = batchStart; i <= batchEnd; i++) {
      const participantId = generateParticipantId(i);
      const docRef = db.collection(COLLECTION).doc(participantId);

      batch.set(docRef, {
        participantId: participantId,
        inUse: false,
        createdAt: new Date(),
        enrolledAt: null,
        enrolledByVisitorId: null,
        enrolledByDeviceInfo: null,
      });
    }

    await batch.commit();
    totalWritten += (batchEnd - batchStart + 1);
    console.log(`Progress: ${totalWritten}/${TOTAL_IDS} (${((totalWritten/TOTAL_IDS)*100).toFixed(1)}%)`);
  }

  console.log(`\nSuccessfully seeded ${totalWritten} participant IDs!`);
  console.log(`Collection: ${COLLECTION}`);
  console.log(`ID range: ${generateParticipantId(1)} - ${generateParticipantId(TOTAL_IDS)}`);
}

// Run the seed
seedParticipants()
  .then(() => {
    console.log('\nDone!');
    process.exit(0);
  })
  .catch((error) => {
    console.error('Error seeding participants:', error.message || error);
    process.exit(1);
  });
