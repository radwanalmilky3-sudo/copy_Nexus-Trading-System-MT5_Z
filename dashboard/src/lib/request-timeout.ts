/** One deadline for the request and its response body, preserving caller cancellation. */
export async function withRequestTimeout<T>(
  operation: (signal: AbortSignal) => Promise<T>,
  callerSignal?: AbortSignal | null,
): Promise<T> {
  const controller = new AbortController();
  const cancel = () => controller.abort(callerSignal?.reason);
  let rejectAborted: (reason: unknown) => void = () => {};
  const aborted = new Promise<never>((_, reject) => { rejectAborted = reject; });
  const onAbort = () => rejectAborted(controller.signal.reason);
  controller.signal.addEventListener('abort', onAbort, { once: true });
  callerSignal?.addEventListener('abort', cancel, { once: true });
  const timer = setTimeout(() => {
    controller.abort(new DOMException(
      'انتهت مهلة الاتصال بالخادم بعد 15 ثانية. يرجى المحاولة مجددًا.',
      'TimeoutError',
    ));
  }, 15_000);

  try {
    if (callerSignal?.aborted) cancel();
    // Observe the rejection even when the caller was already cancelled.
    return await Promise.race([
      aborted,
      controller.signal.aborted ? aborted : operation(controller.signal),
    ]);
  } finally {
    clearTimeout(timer);
    callerSignal?.removeEventListener('abort', cancel);
    controller.signal.removeEventListener('abort', onAbort);
  }
}
