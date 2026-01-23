import admin from 'firebase-admin';
import { createRequire } from 'module';

const require = createRequire(import.meta.url);
const serviceAccount = require('../Keys/r01-redditx-suicide-firebase-adminsdk-fbsvc-306bc4ee85.json');

admin.initializeApp({
  credential: admin.credential.cert(serviceAccount),
  storageBucket: 'r01-redditx-suicide.firebasestorage.app',
});

const bucket = admin.storage().bucket();

async function checkStorage() {
  console.log('Checking Firebase Storage...\n');

  try {
    const [files] = await bucket.getFiles({ prefix: 'screenshots/', maxResults: 20 });

    console.log(`Found ${files.length} files in screenshots/:\n`);

    files.forEach((file) => {
      console.log(`  ${file.name} (${(file.metadata.size / 1024).toFixed(1)} KB)`);
    });

    if (files.length === 0) {
      console.log('  (no screenshots uploaded yet)');
    }
  } catch (e) {
    console.log('Error accessing storage:', e.message);
  }

  process.exit(0);
}

checkStorage().catch(console.error);
