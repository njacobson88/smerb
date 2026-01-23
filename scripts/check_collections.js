import admin from 'firebase-admin';
import { createRequire } from 'module';

const require = createRequire(import.meta.url);
const serviceAccount = require('../Keys/r01-redditx-suicide-firebase-adminsdk-fbsvc-306bc4ee85.json');

admin.initializeApp({
  credential: admin.credential.cert(serviceAccount),
});

const db = admin.firestore();

async function checkCollections() {
  console.log(`Project: ${serviceAccount.project_id}\n`);

  // List all collections
  const collections = await db.listCollections();
  console.log('=== Collections ===');
  for (const col of collections) {
    const snapshot = await col.limit(1).get();
    const countSnap = await col.count().get();
    const count = countSnap.data().count;
    console.log(`  ${col.id}: ${count} documents`);
    if (!snapshot.empty) {
      const sample = snapshot.docs[0].data();
      console.log(`    Sample fields: ${Object.keys(sample).join(', ')}`);
    }
  }

  // Check storage
  console.log('\n=== Firebase Storage ===');
  const bucket = admin.storage().bucket(`${serviceAccount.project_id}.firebasestorage.app`);
  const [files] = await bucket.getFiles({ prefix: 'screenshots/', maxResults: 5 });
  console.log(`Screenshots in storage: ${files.length}+ files`);
  if (files.length > 0) {
    console.log(`  Latest: ${files[files.length - 1].name}`);
  }

  process.exit(0);
}

checkCollections().catch(console.error);
