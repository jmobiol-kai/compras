// Enough of @web/core/utils/patch for `super` inside a prototype patch.
const descriptions = new WeakMap();

function isClassPrototype(obj) {
    return Object.hasOwn(obj, "constructor") && obj.constructor?.prototype === obj;
}

export function patch(obj, extension) {
    let description = descriptions.get(obj);
    if (!description) {
        description = { skeleton: Object.create(Object.getPrototypeOf(obj)) };
        descriptions.set(obj, description);
    }
    for (const [key, descriptor] of Object.entries(Object.getOwnPropertyDescriptors(extension))) {
        const current = Object.getOwnPropertyDescriptor(obj, key);
        if (current) {
            Object.defineProperty(description.skeleton, key, current);
        }
        if (isClassPrototype(obj)) {
            descriptor.enumerable = false;
        }
        Object.defineProperty(obj, key, descriptor);
    }
    description.skeleton = Object.setPrototypeOf(extension, description.skeleton);
}
