// Paste this into your browser console (F12 → Console tab)
// It will diagnose why the sidebar button is not showing

(function diagnoseSidebar() {
  console.log("=== SIDEBAR DIAGNOSTIC ===\n");

  // 1. Check if button exists
  const buttons = document.querySelectorAll('button[aria-label*="sidebar"], button[type="button"]');
  console.log("1. BUTTONS FOUND:", buttons.length);
  buttons.forEach((btn, i) => {
    const rect = btn.getBoundingClientRect();
    const styles = window.getComputedStyle(btn);
    console.log(`   Button ${i}:`, {
      text: btn.innerText || btn.textContent?.slice(0, 20),
      ariaLabel: btn.getAttribute('aria-label'),
      visible: rect.width > 0 && rect.height > 0,
      rect: { top: rect.top, left: rect.left, width: rect.width, height: rect.height },
      display: styles.display,
      visibility: styles.visibility,
      opacity: styles.opacity,
      zIndex: styles.zIndex,
      position: styles.position
    });
  });

  // 2. Check for fixed/absolute positioned elements that might cover it
  const fixedElements = document.querySelectorAll('[style*="fixed"], [style*="absolute"]');
  console.log("\n2. FIXED/ABSOLUTE ELEMENTS near top-left:");
  fixedElements.forEach((el, i) => {
    const rect = el.getBoundingClientRect();
    if (rect.top < 100 && rect.left < 300) {
      console.log(`   Element ${i}:`, el.tagName, {
        class: el.className?.slice(0, 50),
        rect: { top: rect.top, left: rect.left, width: rect.width, height: rect.height },
        zIndex: window.getComputedStyle(el).zIndex
      });
    }
  });

  // 3. Check React state (if exposed)
  console.log("\n3. REACT STATE:");
  console.log("   window.toggleSidebar:", typeof window.toggleSidebar);
  console.log("   window.getSidebarOpen:", typeof window.getSidebarOpen);
  if (window.getSidebarOpen) {
    console.log("   Current sidebarOpen:", window.getSidebarOpen());
  }

  // 4. Check for the specific purple button
  console.log("\n4. PURPLE BUTTON CHECK:");
  const allButtons = document.querySelectorAll('button');
  let foundPurple = false;
  allButtons.forEach((btn, i) => {
    const styles = window.getComputedStyle(btn);
    const bg = styles.backgroundColor;
    if (bg.includes('103') || bg.includes('6720') || bg.includes('rgb(103') || bg.includes('purple') || bg.includes('#6720')) {
      foundPurple = true;
      const rect = btn.getBoundingClientRect();
      console.log(`   Found purple button at index ${i}:`, {
        rect: { top: rect.top, left: rect.left },
        bg: bg,
        display: styles.display,
        visibility: styles.visibility,
        zIndex: styles.zIndex
      });
    }
  });
  if (!foundPurple) console.log("   NO purple button found!");

  // 5. Check for React errors
  console.log("\n5. CONSOLE ERRORS (check above for red text)");

  // 6. Check if sidebar exists
  const sidebars = document.querySelectorAll('aside, nav');
  console.log("\n6. SIDEBAR-LIKE ELEMENTS:", sidebars.length);
  sidebars.forEach((el, i) => {
    const rect = el.getBoundingClientRect();
    if (rect.width > 50) {
      console.log(`   Element ${i} (${el.tagName}):`, {
        class: el.className?.slice(0, 50),
        width: rect.width,
        height: rect.height,
        visible: rect.width > 0 && rect.height > 0
      });
    }
  });

  // 7. Force toggle for testing
  console.log("\n7. FORCING SIDEBAR OPEN...");
  if (window.toggleSidebar) {
    window.toggleSidebar();
    console.log("   Called window.toggleSidebar()");
    setTimeout(() => {
      if (window.getSidebarOpen) {
        console.log("   New state:", window.getSidebarOpen());
      }
      const sidebarsAfter = document.querySelectorAll('aside');
      console.log("   Sidebars now:", sidebarsAfter.length);
    }, 500);
  } else {
    console.log("   window.toggleSidebar NOT AVAILABLE");
  }

  console.log("\n=== END DIAGNOSTIC ===");
})();