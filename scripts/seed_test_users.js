/**
 * Seed script to add 1000 test users (test1 - test1000) for user testing.
 *
 * Usage:
 *   GOOGLE_APPLICATION_CREDENTIALS=/path/to/key.json npm run seed:test
 */

import { initializeApp, cert } from 'firebase-admin/app';
import { getFirestore } from 'firebase-admin/firestore';
import { readFileSync, existsSync } from 'fs';

const PROJECT_ID = 'r01-redditx-suicide';
const COLLECTION = 'valid_participants';
const TOTAL_TEST_USERS = 1000;
const BATCH_SIZE = 500;

/**
 * Initialize Firebase Admin
 */
function initializeFirebase() {
  const serviceAccountPath = process.env.GOOGLE_APPLICATION_CREDENTIALS;

  if (serviceAccountPath && existsSync(serviceAccountPath)) {
    console.log('Using service account from GOOGLE_APPLICATION_CREDENTIALS');
    const serviceAccount = JSON.parse(readFileSync(serviceAccountPath, 'utf8'));
    initializeApp({
      credential: cert(serviceAccount),
      projectId: PROJECT_ID,
    });
  } else {
    console.error('No credentials found. Set GOOGLE_APPLICATION_CREDENTIALS.');
    process.exit(1);
  }

  return getFirestore();
}

/**
 * Seed test users to Firestore
 */
async function seedTestUsers() {
  const db = initializeFirebase();

  console.log(`Creating ${TOTAL_TEST_USERS} test users (test1 - test${TOTAL_TEST_USERS})...`);

  let totalWritten = 0;

  for (let i = 1; i <= TOTAL_TEST_USERS; i += BATCH_SIZE) {
    const batch = db.batch();
    const batchEnd = Math.min(i + BATCH_SIZE - 1, TOTAL_TEST_USERS);

    for (let j = i; j <= batchEnd; j++) {
      const testId = `test${j}`;
      const docRef = db.collection(COLLECTION).doc(testId);

      batch.set(docRef, {
        participantId: testId,
        inUse: false,
        isTestUser: true,
        createdAt: new Date(),
        enrolledAt: null,
        enrolledByVisitorId: null,
        enrolledByDeviceInfo: null,
      });
    }

    await batch.commit();
    totalWritten += (batchEnd - i + 1);
    console.log(`Progress: ${totalWritten}/${TOTAL_TEST_USERS} (${((totalWritten/TOTAL_TEST_USERS)*100).toFixed(1)}%)`);
  }

  console.log(`\nSuccessfully created ${totalWritten} test users!`);
  console.log(`IDs: test1 - test${TOTAL_TEST_USERS}`);
}

seedTestUsers()
  .then(() => {
    console.log('\nDone!');
    process.exit(0);
  })
  .catch((error) => {
    console.error('Error:', error.message || error);
    process.exit(1);
  });
