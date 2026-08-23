export default class Stage14PlaywrightReporter {
  constructor() {
    this.passed = 0;
    this.failed = 0;
  }

  onTestEnd(_test, result) {
    if (result.status === "passed") {
      this.passed += 1;
      return;
    }
    this.failed += 1;
  }

  onEnd() {
    console.log(`stage14_playwright_report passed=${this.passed} failed=${this.failed}`);
  }
}
