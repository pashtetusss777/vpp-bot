package dev.example.vanillaplus;

import org.junit.jupiter.api.Test;

import static org.junit.jupiter.api.Assertions.*;

class StringsTest {

    @Test
    void prefixContainsName() {
        String prefix = Strings.PREFIX.get();
        assertTrue(prefix.contains("[Vanilla++]"));
    }

    @Test
    void errorConstantsAreJson() {
        assertEquals("{\"error\":\"method_not_allowed\"}", Strings.ERROR_METHOD_NOT_ALLOWED.get());
        assertEquals("{\"status\":\"ok\"}", Strings.STATUS_OK.get());
    }
}
