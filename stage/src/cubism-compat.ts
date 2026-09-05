interface CubismCoreModel {
  getDrawableRenderOrders?: () => ArrayLike<number> | undefined;
  getModel?: () => {
    getRenderOrders?: () => ArrayLike<number> | undefined;
    renderOrders?: ArrayLike<number>;
  };
}

function hasOrders(value: ArrayLike<number> | undefined): value is ArrayLike<number> {
  return value !== undefined && typeof value.length === "number" && value.length > 0;
}

/**
 * Cubism Core 5 moved render orders behind Model.getRenderOrders(), while the
 * Cubism 4 renderer used by pixi-live2d-display still asks its wrapper for the
 * old drawable render-order view. Bridge only that API difference.
 */
export function ensureCubismRenderOrders(coreModelValue: unknown): "native" | "patched" {
  if (!coreModelValue || typeof coreModelValue !== "object") {
    throw new Error("The Cubism model did not expose a compatible core model");
  }

  const coreModel = coreModelValue as CubismCoreModel;
  const nativeOrders = coreModel.getDrawableRenderOrders?.call(coreModel);
  if (hasOrders(nativeOrders)) return "native";

  const rawModel = coreModel.getModel?.call(coreModel);
  const readOrders = () => rawModel?.getRenderOrders?.call(rawModel) ?? rawModel?.renderOrders;
  if (!hasOrders(readOrders())) {
    throw new Error("The selected Cubism Core did not expose drawable render orders");
  }

  coreModel.getDrawableRenderOrders = () => {
    const orders = readOrders();
    if (!hasOrders(orders)) throw new Error("Cubism drawable render orders became unavailable");
    return orders;
  };
  return "patched";
}
