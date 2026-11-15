import { showToast, Toast } from "@raycast/api";

/**
 * Run a file write. On an error (for example a full disk), show it and return false, so the caller can
 * stop: a change that was not written must never look saved.
 */
export async function tryWrite(what: string, write: () => void): Promise<boolean> {
  try {
    write();
    return true;
  } catch (error) {
    await showToast({ style: Toast.Style.Failure, title: `Could not ${what}`, message: String(error) });
    return false;
  }
}
