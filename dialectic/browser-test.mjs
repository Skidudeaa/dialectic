/**
 * Browser test suite for Dialectic frontend.
 * Connects to a Chrome instance running with --no-sandbox via CDP.
 */
import { chromium } from 'playwright';
import { writeFileSync, mkdirSync } from 'fs';

const SCREENSHOTS_DIR = '/root/DwoodAmo/dialectic/test-screenshots';
const BASE_URL = 'http://localhost:3000';
const API_URL = 'http://localhost:8000';

mkdirSync(SCREENSHOTS_DIR, { recursive: true });

const results = {
  tests: [],
  consoleMessages: { appHtml: [], indexHtml: [] },
  screenshotsTaken: [],
  visualBugs: [],
  interactionIssues: [],
  summary: ''
};

function logTest(name, status, details = '') {
  const result = { name, status, details };
  results.tests.push(result);
  console.log(`[${status}] ${name}${details ? ': ' + details : ''}`);
}

async function takeScreenshot(page, name) {
  const path = `${SCREENSHOTS_DIR}/${name}.png`;
  await page.screenshot({ path, fullPage: false });
  results.screenshotsTaken.push(path);
  console.log(`  Screenshot: ${path}`);
  return path;
}

async function run() {
  let browser;
  try {
    // Connect to the running Chrome instance via CDP
    browser = await chromium.connectOverCDP('http://localhost:9222');
    console.log('Connected to Chrome via CDP');
  } catch (e) {
    console.error('Failed to connect to Chrome via CDP:', e.message);
    process.exit(1);
  }

  const context = browser.contexts()[0] || await browser.newContext();
  let page = context.pages()[0] || await context.newPage();

  // Collect console messages for app.html
  const appConsoleMessages = [];
  page.on('console', msg => {
    appConsoleMessages.push({ type: msg.type(), text: msg.text() });
  });
  page.on('pageerror', err => {
    appConsoleMessages.push({ type: 'error', text: `PAGE ERROR: ${err.message}` });
  });

  // ========== TEST 1: Page Load ==========
  console.log('\n=== TEST 1: Page Load (app.html) ===');
  try {
    const response = await page.goto(`${BASE_URL}/app.html`, { waitUntil: 'networkidle', timeout: 15000 });
    const status = response?.status();
    if (status === 200) {
      logTest('Page Load (app.html)', 'PASS', `HTTP ${status}`);
    } else {
      logTest('Page Load (app.html)', 'FAIL', `HTTP ${status}`);
    }

    // Wait for content to render
    await page.waitForTimeout(2000);

    const title = await page.title();
    console.log(`  Page title: ${title}`);

    // Check if key elements exist
    const bodyText = await page.textContent('body');
    console.log(`  Body text length: ${bodyText.length}`);

    await takeScreenshot(page, '01-page-load');

    // Check for visible form elements
    const hasAuthForm = await page.$('form, input[type="email"], input[type="password"], .auth-panel, #auth-panel, [data-auth]');
    console.log(`  Auth form present: ${!!hasAuthForm}`);

  } catch (e) {
    logTest('Page Load (app.html)', 'FAIL', e.message);
  }

  // Check console errors after page load
  const jsErrors = appConsoleMessages.filter(m => m.type === 'error');
  if (jsErrors.length > 0) {
    logTest('Console Errors on Load', 'WARN', `${jsErrors.length} errors found`);
    jsErrors.forEach(e => console.log(`  ERROR: ${e.text}`));
  } else {
    logTest('Console Errors on Load', 'PASS', 'No JS errors');
  }

  // ========== TEST 2: Auth Flow ==========
  console.log('\n=== TEST 2: Auth Flow ===');
  try {
    // Look for auth-related elements
    const emailInput = await page.$('input[type="email"], input[name="email"], #email, #signup-email, #login-email');
    const passwordInput = await page.$('input[type="password"], input[name="password"], #password, #signup-password, #login-password');
    const displayNameInput = await page.$('input[name="displayName"], input[name="display_name"], #display-name, #signup-name, #displayName');

    if (emailInput && passwordInput) {
      console.log('  Found auth form fields');

      // Check if there's a signup tab/toggle
      const signupTab = await page.$('button:has-text("Sign Up"), a:has-text("Sign Up"), [data-tab="signup"], .signup-tab, #signup-tab');
      if (signupTab) {
        console.log('  Found signup tab, clicking...');
        await signupTab.click();
        await page.waitForTimeout(500);
      }

      // Try to fill signup form
      const signupEmailInput = await page.$('input[type="email"]:visible, input[name="email"]:visible, #signup-email:visible');
      const signupPasswordInput = await page.$('input[type="password"]:visible, input[name="password"]:visible, #signup-password:visible');
      const signupNameInput = await page.$('input[name="displayName"]:visible, input[name="display_name"]:visible, #signup-name:visible, #displayName:visible, input[placeholder*="name"]:visible, input[placeholder*="Name"]:visible');

      if (signupEmailInput) {
        await signupEmailInput.fill('browser-test@dialectic.dev');
        console.log('  Filled email');
      }
      if (signupNameInput) {
        await signupNameInput.fill('Browser Tester');
        console.log('  Filled display name');
      }
      if (signupPasswordInput) {
        await signupPasswordInput.fill('TestPass123!');
        console.log('  Filled password');
      }

      await takeScreenshot(page, '02-auth-form-filled');

      // Look for submit button
      const submitBtn = await page.$('button[type="submit"], button:has-text("Sign Up"), button:has-text("Create Account"), button:has-text("Register"), .auth-submit');
      if (submitBtn) {
        console.log('  Clicking submit...');
        await submitBtn.click();
        await page.waitForTimeout(3000);

        await takeScreenshot(page, '03-after-auth-attempt');

        // Check if auth succeeded - look for room creation UI or main app
        const roomUI = await page.$('#rooms, .room-list, .rooms-panel, [data-room], button:has-text("Create Room"), button:has-text("New Room")');
        const errorMsg = await page.$('.error, .auth-error, [role="alert"]');

        if (roomUI) {
          logTest('Auth Flow - Signup', 'PASS', 'Successfully signed up, room UI visible');
        } else if (errorMsg) {
          const errorText = await errorMsg.textContent();
          console.log(`  Auth error: ${errorText}`);

          // Try login instead
          console.log('  Trying login flow instead...');
          const loginTab = await page.$('button:has-text("Login"), button:has-text("Log In"), button:has-text("Sign In"), a:has-text("Login"), [data-tab="login"], .login-tab, #login-tab');
          if (loginTab) {
            await loginTab.click();
            await page.waitForTimeout(500);
          }

          const loginEmail = await page.$('input[type="email"]:visible, #login-email:visible');
          const loginPassword = await page.$('input[type="password"]:visible, #login-password:visible');

          if (loginEmail) await loginEmail.fill('browser-test@dialectic.dev');
          if (loginPassword) await loginPassword.fill('TestPass123!');

          const loginBtn = await page.$('button[type="submit"]:visible, button:has-text("Log In"):visible, button:has-text("Login"):visible, button:has-text("Sign In"):visible');
          if (loginBtn) {
            await loginBtn.click();
            await page.waitForTimeout(3000);
          }

          await takeScreenshot(page, '03b-after-login-attempt');

          const roomUIAfterLogin = await page.$('#rooms, .room-list, .rooms-panel, [data-room], button:has-text("Create Room")');
          if (roomUIAfterLogin) {
            logTest('Auth Flow - Login', 'PASS', 'Successfully logged in');
          } else {
            logTest('Auth Flow - Login', 'FAIL', 'Could not authenticate');
          }
        } else {
          // Check page state
          const pageContent = await page.textContent('body');
          logTest('Auth Flow', 'WARN', `Auth state unclear. Page text length: ${pageContent.length}`);
        }
      } else {
        logTest('Auth Flow', 'WARN', 'No submit button found');
      }
    } else {
      // Maybe the page uses a different auth pattern
      console.log('  Standard email/password inputs not found');
      console.log('  Checking for alternative auth patterns...');

      // List all inputs on the page
      const inputs = await page.$$eval('input', els => els.map(e => ({
        type: e.type,
        name: e.name,
        id: e.id,
        placeholder: e.placeholder,
        class: e.className
      })));
      console.log('  All inputs:', JSON.stringify(inputs, null, 2));

      // List all buttons
      const buttons = await page.$$eval('button', els => els.map(e => ({
        text: e.textContent.trim(),
        type: e.type,
        id: e.id,
        class: e.className
      })));
      console.log('  All buttons:', JSON.stringify(buttons, null, 2));

      logTest('Auth Flow', 'SKIP', 'No standard auth form found');
    }
  } catch (e) {
    logTest('Auth Flow', 'FAIL', e.message);
    await takeScreenshot(page, '02-auth-error');
  }

  // ========== TEST 3: Room Creation ==========
  console.log('\n=== TEST 3: Room Creation ===');
  try {
    // Look for room creation UI
    const createRoomBtn = await page.$('button:has-text("Create"), button:has-text("New Room"), button:has-text("+"), .create-room, #create-room, [data-action="create-room"]');

    if (createRoomBtn) {
      console.log('  Found create room button');
      await createRoomBtn.click();
      await page.waitForTimeout(1000);

      // Look for room name input
      const roomNameInput = await page.$('input[name="roomName"], input[name="room_name"], input[placeholder*="room"], input[placeholder*="Room"], #room-name, #roomName');
      if (roomNameInput) {
        await roomNameInput.fill('Browser QA Room');
        console.log('  Filled room name');

        // Submit
        const submitBtn = await page.$('button[type="submit"], button:has-text("Create"), button:has-text("OK"), button:has-text("Save")');
        if (submitBtn) {
          await submitBtn.click();
          await page.waitForTimeout(2000);
        }

        await takeScreenshot(page, '04-room-created');
        logTest('Room Creation', 'PASS', 'Room creation flow completed');
      } else {
        // Maybe it's a modal or different flow
        await takeScreenshot(page, '04-room-creation-ui');
        logTest('Room Creation', 'WARN', 'Create button found but no room name input');
      }
    } else {
      // Try alternative - maybe rooms are shown in a list
      const roomItems = await page.$$('.room-item, .room-card, [data-room-id], .room');
      console.log(`  Room items found: ${roomItems.length}`);
      await takeScreenshot(page, '04-no-create-room-btn');
      logTest('Room Creation', 'SKIP', 'No create room button found');
    }
  } catch (e) {
    logTest('Room Creation', 'FAIL', e.message);
  }

  // ========== TEST 4: Messaging ==========
  console.log('\n=== TEST 4: Messaging ===');
  try {
    const messageInput = await page.$('textarea, input[type="text"][placeholder*="message"], input[type="text"][placeholder*="Message"], #message-input, .message-input, [data-message-input]');

    if (messageInput) {
      console.log('  Found message input');
      await messageInput.fill('Hello from browser test!');
      await page.waitForTimeout(500);

      // Try to send
      const sendBtn = await page.$('button:has-text("Send"), button[type="submit"], .send-btn, #send-btn');
      if (sendBtn) {
        await sendBtn.click();
      } else {
        // Try pressing Enter
        await messageInput.press('Enter');
      }

      await page.waitForTimeout(2000);

      // Check if message appears
      const messages = await page.$$('.message, .message-bubble, [data-message], .msg');
      console.log(`  Messages visible: ${messages.length}`);

      await takeScreenshot(page, '05-message-sent');

      if (messages.length > 0) {
        logTest('Messaging', 'PASS', `${messages.length} messages visible`);
      } else {
        logTest('Messaging', 'WARN', 'Message sent but none visible in DOM');
      }
    } else {
      console.log('  No message input found');

      // List all textareas and text inputs
      const textInputs = await page.$$eval('textarea, input[type="text"]', els => els.map(e => ({
        tag: e.tagName,
        id: e.id,
        name: e.name,
        placeholder: e.placeholder,
        class: e.className
      })));
      console.log('  All text inputs:', JSON.stringify(textInputs, null, 2));

      await takeScreenshot(page, '05-no-message-input');
      logTest('Messaging', 'SKIP', 'No message input found (may need auth first)');
    }
  } catch (e) {
    logTest('Messaging', 'FAIL', e.message);
  }

  // ========== TEST 5: Visual Inspection ==========
  console.log('\n=== TEST 5: Visual Inspection ===');
  try {
    // Overall layout
    await takeScreenshot(page, '06-overall-layout');

    // Check viewport size and layout
    const layoutInfo = await page.evaluate(() => {
      const sidebar = document.querySelector('.sidebar, #sidebar, .rooms-panel, aside');
      const mainContent = document.querySelector('.main-content, main, .chat-area, #chat-area, .thread-panel');
      const detailPanel = document.querySelector('.detail-panel, .settings-panel, .right-panel, .memories-panel');

      return {
        viewportWidth: window.innerWidth,
        viewportHeight: window.innerHeight,
        hasSidebar: !!sidebar,
        sidebarWidth: sidebar?.getBoundingClientRect()?.width || 0,
        hasMainContent: !!mainContent,
        mainContentWidth: mainContent?.getBoundingClientRect()?.width || 0,
        hasDetailPanel: !!detailPanel,
        detailPanelWidth: detailPanel?.getBoundingClientRect()?.width || 0,
        bodyBgColor: getComputedStyle(document.body).backgroundColor,
        bodyColor: getComputedStyle(document.body).color,
        allSections: Array.from(document.querySelectorAll('section, .panel, aside, main, nav')).map(el => ({
          tag: el.tagName,
          class: el.className,
          id: el.id,
          width: el.getBoundingClientRect().width,
          height: el.getBoundingClientRect().height
        }))
      };
    });

    console.log('  Layout info:', JSON.stringify(layoutInfo, null, 2));

    if (layoutInfo.hasSidebar && layoutInfo.hasMainContent) {
      logTest('Visual - Layout', 'PASS', `3-column layout detected (sidebar: ${layoutInfo.sidebarWidth}px, main: ${layoutInfo.mainContentWidth}px, detail: ${layoutInfo.detailPanelWidth}px)`);
    } else if (layoutInfo.hasSidebar || layoutInfo.hasMainContent) {
      logTest('Visual - Layout', 'WARN', 'Partial layout detected');
    } else {
      logTest('Visual - Layout', 'INFO', 'Layout structure needs investigation');
    }

    // Check for message bubbles and color distinction
    const messageInfo = await page.evaluate(() => {
      const messages = document.querySelectorAll('.message, .message-bubble, [data-speaker], [data-message]');
      return Array.from(messages).slice(0, 5).map(m => ({
        class: m.className,
        bgColor: getComputedStyle(m).backgroundColor,
        text: m.textContent.substring(0, 50),
        speakerType: m.dataset?.speaker || m.dataset?.speakerType || ''
      }));
    });

    if (messageInfo.length > 0) {
      console.log('  Message bubbles:', JSON.stringify(messageInfo, null, 2));
      logTest('Visual - Message Bubbles', 'PASS', `${messageInfo.length} message bubbles found`);
    } else {
      logTest('Visual - Message Bubbles', 'SKIP', 'No message bubbles visible');
    }

    // Check dark theme
    const isDark = await page.evaluate(() => {
      const bg = getComputedStyle(document.body).backgroundColor;
      const match = bg.match(/\d+/g);
      if (match) {
        const [r, g, b] = match.map(Number);
        return (r + g + b) / 3 < 128;
      }
      return false;
    });
    console.log(`  Dark theme: ${isDark}`);
    logTest('Visual - Theme', 'INFO', isDark ? 'Dark theme detected' : 'Light theme detected');

  } catch (e) {
    logTest('Visual Inspection', 'FAIL', e.message);
  }

  // ========== TEST 6: Keyboard Shortcuts ==========
  console.log('\n=== TEST 6: Keyboard Shortcuts ===');
  try {
    // Press "?" to check for shortcuts overlay
    await page.keyboard.press('?');
    await page.waitForTimeout(1000);

    const modal = await page.$('.modal, .overlay, .shortcuts-modal, .keyboard-shortcuts, [role="dialog"], .dialog');
    if (modal) {
      console.log('  Shortcuts modal appeared');
      await takeScreenshot(page, '07-shortcuts-modal');
      logTest('Keyboard Shortcuts - ? key', 'PASS', 'Modal appeared');

      // Press Escape to close
      await page.keyboard.press('Escape');
      await page.waitForTimeout(500);

      const modalAfterEsc = await page.$('.modal:visible, .overlay:visible, [role="dialog"]:visible');
      if (!modalAfterEsc) {
        logTest('Keyboard Shortcuts - Escape', 'PASS', 'Modal closed');
      } else {
        logTest('Keyboard Shortcuts - Escape', 'WARN', 'Modal may not have closed');
      }
    } else {
      console.log('  No shortcuts modal appeared');
      await takeScreenshot(page, '07-no-shortcuts-modal');
      logTest('Keyboard Shortcuts - ? key', 'SKIP', 'No modal appeared (may be context-dependent)');
    }
  } catch (e) {
    logTest('Keyboard Shortcuts', 'FAIL', e.message);
  }

  // ========== TEST 7: Console Errors ==========
  console.log('\n=== TEST 7: Console Errors Summary (app.html) ===');
  results.consoleMessages.appHtml = appConsoleMessages;
  const errors = appConsoleMessages.filter(m => m.type === 'error');
  const warnings = appConsoleMessages.filter(m => m.type === 'warning');
  console.log(`  Total console messages: ${appConsoleMessages.length}`);
  console.log(`  Errors: ${errors.length}`);
  console.log(`  Warnings: ${warnings.length}`);

  errors.forEach(e => console.log(`  [ERROR] ${e.text}`));
  warnings.forEach(w => console.log(`  [WARN] ${w.text}`));

  if (errors.length === 0) {
    logTest('Console Errors (app.html)', 'PASS', 'No JS errors');
  } else {
    logTest('Console Errors (app.html)', 'FAIL', `${errors.length} errors: ${errors.map(e => e.text).join('; ').substring(0, 200)}`);
  }

  // ========== TEST 8: Compare index.html ==========
  console.log('\n=== TEST 8: Check index.html ===');
  try {
    // Navigate to index.html
    const indexConsoleMessages = [];
    page.removeAllListeners('console');
    page.removeAllListeners('pageerror');
    page.on('console', msg => {
      indexConsoleMessages.push({ type: msg.type(), text: msg.text() });
    });
    page.on('pageerror', err => {
      indexConsoleMessages.push({ type: 'error', text: `PAGE ERROR: ${err.message}` });
    });

    const indexResponse = await page.goto(`${BASE_URL}/index.html`, { waitUntil: 'networkidle', timeout: 15000 });
    await page.waitForTimeout(2000);

    const indexStatus = indexResponse?.status();
    console.log(`  HTTP status: ${indexStatus}`);

    await takeScreenshot(page, '08-index-html');

    const indexTitle = await page.title();
    console.log(`  Page title: ${indexTitle}`);

    const indexBodyText = await page.textContent('body');
    console.log(`  Body text length: ${indexBodyText.length}`);

    // Check for key differences
    const indexLayout = await page.evaluate(() => {
      return {
        hasChat: !!document.querySelector('.chat, #chat, .messages'),
        hasAuth: !!document.querySelector('form, .auth, #auth, input[type="email"]'),
        hasRooms: !!document.querySelector('.rooms, #rooms, .room-list'),
        allIds: Array.from(document.querySelectorAll('[id]')).map(e => e.id).slice(0, 30),
        allClasses: [...new Set(Array.from(document.querySelectorAll('[class]')).flatMap(e => [...e.classList]))].slice(0, 30)
      };
    });
    console.log('  index.html layout:', JSON.stringify(indexLayout, null, 2));

    results.consoleMessages.indexHtml = indexConsoleMessages;

    const indexErrors = indexConsoleMessages.filter(m => m.type === 'error');
    if (indexErrors.length === 0) {
      logTest('Console Errors (index.html)', 'PASS', 'No JS errors');
    } else {
      logTest('Console Errors (index.html)', 'FAIL', `${indexErrors.length} errors`);
      indexErrors.forEach(e => console.log(`  [ERROR] ${e.text}`));
    }

    logTest('index.html Load', indexStatus === 200 ? 'PASS' : 'FAIL', `HTTP ${indexStatus}`);

  } catch (e) {
    logTest('index.html Load', 'FAIL', e.message);
  }

  // ========== FINAL SUMMARY ==========
  console.log('\n' + '='.repeat(60));
  console.log('BROWSER TEST RESULTS SUMMARY');
  console.log('='.repeat(60));

  const passed = results.tests.filter(t => t.status === 'PASS').length;
  const failed = results.tests.filter(t => t.status === 'FAIL').length;
  const warned = results.tests.filter(t => t.status === 'WARN').length;
  const skipped = results.tests.filter(t => t.status === 'SKIP').length;
  const info = results.tests.filter(t => t.status === 'INFO').length;

  console.log(`\nPASSED: ${passed}  |  FAILED: ${failed}  |  WARN: ${warned}  |  SKIPPED: ${skipped}  |  INFO: ${info}`);
  console.log(`\nScreenshots saved: ${results.screenshotsTaken.length}`);
  results.screenshotsTaken.forEach(s => console.log(`  ${s}`));

  console.log('\nAll test results:');
  results.tests.forEach(t => {
    console.log(`  [${t.status}] ${t.name}${t.details ? ' - ' + t.details : ''}`);
  });

  results.summary = `Browser Tests: ${passed} passed, ${failed} failed, ${warned} warnings, ${skipped} skipped`;

  // Save full results to file
  writeFileSync(
    `${SCREENSHOTS_DIR}/test-results.json`,
    JSON.stringify(results, null, 2)
  );
  console.log(`\nFull results saved to: ${SCREENSHOTS_DIR}/test-results.json`);

  await browser.close();
}

run().catch(e => {
  console.error('Fatal error:', e);
  process.exit(1);
});
