/**
 * Seed script to populate Firestore with 10,000 valid participant IDs.
 * IDs are randomly generated 9-digit numbers (no duplicates).
 *
 * Usage:
 *   1. Make sure you're logged in: firebase login
 *   2. Run: GOOGLE_APPLICATION_CREDENTIALS=/path/to/key.json npm run seed
 */

import { initializeApp, cert } from 'firebase-admin/app';
import { getFirestore } from 'firebase-admin/firestore';
import { readFileSync, existsSync } from 'fs';

const PROJECT_ID = 'r01-redditx-suicide';
const COLLECTION = 'valid_participants';
const TOTAL_IDS = 10000;
const BATCH_SIZE = 500; // Firestore batch limit

/**
 * Generate a random 9-digit number as a string with leading zeros if needed
 */
function generateRandomParticipantId() {
  // Generate random number between 0 and 999999999
  const num = Math.floor(Math.random() * 1000000000);
  return String(num).padStart(9, '0');
}

/**
 * Generate a set of unique random 9-digit participant IDs
 */
function generateUniqueParticipantIds(count) {
  const ids = new Set();

  console.log(`Generating ${count} unique random 9-digit IDs...`);

  while (ids.size < count) {
    ids.add(generateRandomParticipantId());

    // Progress update every 1000
    if (ids.size % 1000 === 0) {
      console.log(`Generated ${ids.size}/${count} unique IDs...`);
    }
  }

  return Array.from(ids);
}

/**
 * Initialize Firebase Admin using service account from environment
 */
async function initializeFirebase() {
  const serviceAccountPath = process.env.GOOGLE_APPLICATION_CREDENTIALS;

  if (serviceAccountPath && existsSync(serviceAccountPath)) {
    console.log('Using service account from GOOGLE_APPLICATION_CREDENTIALS');
    const serviceAccount = JSON.parse(readFileSync(serviceAccountPath, 'utf8'));
    initializeApp({
      credential: cert(serviceAccount),
      projectId: PROJECT_ID,
    });
  } else {
    console.error(`
No credentials found. Please set GOOGLE_APPLICATION_CREDENTIALS:

  GOOGLE_APPLICATION_CREDENTIALS=/path/to/service-account.json npm run seed
`);
    process.exit(1);
  }

  return getFirestore();
}

/**
 * Delete all existing documents in the collection
 */
async function clearCollection(db) {
  console.log(`Clearing existing ${COLLECTION} collection...`);

  const collectionRef = db.collection(COLLECTION);
  const snapshot = await collectionRef.limit(500).get();

  if (snapshot.empty) {
    console.log('Collection is empty, nothing to clear.');
    return;
  }

  let totalDeleted = 0;
  let docs = snapshot.docs;

  while (docs.length > 0) {
    const batch = db.batch();
    docs.forEach(doc => batch.delete(doc.ref));
    await batch.commit();
    totalDeleted += docs.length;
    console.log(`Deleted ${totalDeleted} documents...`);

    const nextSnapshot = await collectionRef.limit(500).get();
    docs = nextSnapshot.docs;
  }

  console.log(`Cleared ${totalDeleted} existing documents.`);
}

/**
 * Seed participant IDs to Firestore in batches
 */
async function seedParticipants() {
  const db = await initializeFirebase();

  // Clear existing data first
  await clearCollection(db);

  // Generate unique random IDs
  const participantIds = generateUniqueParticipantIds(TOTAL_IDS);

  console.log(`\nStarting to seed ${TOTAL_IDS} participant IDs...`);

  let totalWritten = 0;

  for (let i = 0; i < participantIds.length; i += BATCH_SIZE) {
    const batch = db.batch();
    const batchIds = participantIds.slice(i, i + BATCH_SIZE);

    for (const participantId of batchIds) {
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
    totalWritten += batchIds.length;
    console.log(`Progress: ${totalWritten}/${TOTAL_IDS} (${((totalWritten/TOTAL_IDS)*100).toFixed(1)}%)`);
  }

  // Show some sample IDs
  const sampleIds = participantIds.slice(0, 5);

  console.log(`\nSuccessfully seeded ${totalWritten} participant IDs!`);
  console.log(`Collection: ${COLLECTION}`);
  console.log(`Sample IDs: ${sampleIds.join(', ')}...`);
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
