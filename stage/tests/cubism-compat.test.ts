import { describe, expect, it, vi } from "vitest";

import { ensureCubismRenderOrders } from "../src/cubism-compat";

describe("ensureCubismRenderOrders", () => {
  it("keeps the native Cubism 4 render-order accessor", () => {
    const orders = new Int32Array([1, 0]);
    const getDrawableRenderOrders = vi.fn(() => orders);
    const coreModel = { getDrawableRenderOrders };

    expect(ensureCubismRenderOrders(coreModel)).toBe("native");
    expect(coreModel.getDrawableRenderOrders()).toBe(orders);
  });

  it("bridges the Cubism 5 render-order accessor", () => {
    const orders = new Int32Array([2, 0, 1]);
    const coreModel = {
      getDrawableRenderOrders: () => undefined,
      getModel: () => ({ getRenderOrders: () => orders }),
    };

    expect(ensureCubismRenderOrders(coreModel)).toBe("patched");
    expect(coreModel.getDrawableRenderOrders()).toBe(orders);
  });

  it("rejects a core model without render orders", () => {
    expect(() => ensureCubismRenderOrders({ getDrawableRenderOrders: () => undefined })).toThrow(
      "did not expose drawable render orders",
    );
  });
});
