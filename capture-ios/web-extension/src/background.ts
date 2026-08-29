import { installBackground, type BackgroundBrowser } from "./background-controller";
import { NATIVE_APPLICATION_IDENTIFIER } from "./config";

declare const browser: BackgroundBrowser;

installBackground(browser, NATIVE_APPLICATION_IDENTIFIER);
